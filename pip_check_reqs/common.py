"""Common functions."""

from __future__ import annotations

import ast
import collections
import fnmatch
import importlib.metadata
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.markers import Marker
from packaging.utils import NormalizedName, canonicalize_name
from pip._internal.commands.show import (
    _PackageInfo,  # pyright: ignore[reportPrivateUsage]
    search_packages_info,
)
from pip._internal.network.session import PipSession
from pip._internal.req.constructors import install_req_from_line
from pip._internal.req.req_file import ParsedRequirement, parse_requirements
from pip._internal.utils.urls import url_to_path

from . import __version__

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Generator, Iterable
    from typing import NoReturn, TextIO

log = logging.getLogger(__name__)


@cache
def cached_resolve_path(path: Path) -> Path:
    return path.resolve()


# This is a slow operation.
# It only happens once when calling the CLI, but it is hit many times in
# tests.
# We cache the result to speed up tests.
@cache
def get_packages_info() -> list[_PackageInfo]:
    all_pkgs: list[str] = [
        dist.metadata["Name"]  # pyright: ignore[reportUnknownMemberType]
        for dist in importlib.metadata.distributions()
    ]

    return list(search_packages_info(query=all_pkgs, include_files=True))


@dataclass
class FoundModule:
    """A module with uses in the source."""

    modname: str
    filename: Path
    locations: list[tuple[str, int]] = field(
        default_factory=list[tuple[str, int]],
    )

    def __post_init__(self) -> None:
        self.filename = Path(self.filename).resolve()


@dataclass
class ImportedModules:
    """The modules which the scanned source imports."""

    found: dict[str, FoundModule]
    """Modules which we found in the environment, keyed by module name."""

    uninstalled: dict[str, list[tuple[str, int]]]
    """Top-level modules which are not installed, keyed by module name.

    Each value is the list of ``(filename, line number)`` locations which
    import the module.
    """


_IMPORT_ERROR_NAMES = frozenset({"ImportError", "ModuleNotFoundError"})


def _catches_import_error(*, handler: ast.ExceptHandler) -> bool:
    """Whether an ``except`` clause catches an import which is not installed.

    A bare ``except`` catches everything, so it counts.
    """
    if handler.type is None:
        return True

    caught = (
        handler.type.elts
        if isinstance(handler.type, ast.Tuple)
        else [handler.type]
    )
    for exception in caught:
        if isinstance(exception, ast.Name):
            name = exception.id
        elif isinstance(exception, ast.Attribute):
            # An exception may be given by a dotted path, as
            # ``builtins.ImportError`` is.
            name = exception.attr
        else:
            continue
        if name in _IMPORT_ERROR_NAMES:
            return True
    return False


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, ignore_modules_function: Callable[[str], bool]) -> None:
        super().__init__()
        self._ignore_modules_function = ignore_modules_function
        self._modules: dict[str, FoundModule] = {}
        self._uninstalled: dict[str, list[tuple[str, int]]] = {}
        self._location: str | None = None
        self._optional_import_depth = 0

    def set_location(self, *, location: str) -> None:
        self._location = location

    # Ignore the name error as we are overriding the method.
    def visit_Import(  # pylint: disable=invalid-name
        self,
        node: ast.Import,
    ) -> None:
        for alias in node.names:
            self._add_module(alias.name, node.lineno)

    # Ignore the name error as we are overriding the method.
    def visit_ImportFrom(  # pylint: disable=invalid-name
        self,
        node: ast.ImportFrom,
    ) -> None:
        if node.module == "__future__":
            # not an actual module
            return
        if node.module is None or node.level != 0:
            # relative import
            return
        if not self._module_exists(modname=node.module):
            self._record_uninstalled(modname=node.module, lineno=node.lineno)
            return
        for alias in node.names:
            self._add_module(node.module + "." + alias.name, node.lineno)

    # Ignore the name error as we are overriding the method.
    def visit_Try(  # pylint: disable=invalid-name
        self,
        node: ast.Try,
    ) -> None:
        """Visit a ``try`` statement, noting imports it makes optional.

        A soft dependency is imported in a ``try`` block which catches
        ``ImportError``, so the code runs whether or not it is installed.
        Such an import is deliberately optional, so we do not report it as
        an import we could not resolve.
        """
        optional = any(
            _catches_import_error(handler=handler) for handler in node.handlers
        )
        self._optional_import_depth += int(optional)
        for statement in node.body:
            self.visit(statement)
        self._optional_import_depth -= int(optional)

        # An import in a handler, in ``else`` or in ``finally`` is not
        # guarded by this ``try``, so we treat it as any other import.
        unguarded: list[ast.AST] = [
            *node.handlers,
            *node.orelse,
            *node.finalbody,
        ]
        for node_to_visit in unguarded:
            self.visit(node_to_visit)

    @staticmethod
    def _module_exists(*, modname: str) -> bool:
        modname_parts_progress: list[str] = []
        for modname_part in modname.split("."):
            name = ".".join([*modname_parts_progress, modname_part])
            try:
                module_spec = find_spec(name=name)
            except (ModuleNotFoundError, ValueError):
                return False
            if module_spec is None:
                return False
            modname_parts_progress.append(modname_part)
        return True

    def _record_uninstalled(self, *, modname: str, lineno: int) -> None:
        """Note an import which we could not resolve to an installed module.

        We only note the import when its top-level module is missing, which
        is what an uninstalled distribution looks like. A missing sub-module
        of an installed distribution is a different problem, and the
        distribution which would provide it is checked already.
        """
        if self._optional_import_depth:
            # The import is a soft dependency, so the code tolerates the
            # module not being installed and there is nothing to report.
            return

        top_level_name = modname.split(".", maxsplit=1)[0]
        # An ignore glob may name either the dotted import path, as it may
        # for an installed module, or just the top-level module which we
        # report.
        if self._ignore_modules_function(modname) or (
            self._ignore_modules_function(top_level_name)
        ):
            return

        try:
            module_spec = find_spec(name=top_level_name)
        except ValueError:
            # The module has no ``__spec__`` attribute, as ``__main__`` does
            # not, so it is available rather than missing.
            return

        if module_spec is not None:
            return

        assert isinstance(self._location, str)
        locations = self._uninstalled.setdefault(top_level_name, [])
        locations.append((self._location, lineno))

    def _add_module(self, modname: str, lineno: int) -> None:
        if self._ignore_modules_function(modname):
            return

        modname_parts_progress: list[str] = []
        for modname_part in modname.split("."):
            name = ".".join([*modname_parts_progress, modname_part])
            try:
                module_spec = find_spec(name=name)
            except ValueError:
                # The module has no __spec__ attribute.
                # For example, if importing __main__.
                return

            if module_spec is None:
                # The component specified at this point is not installed.
                self._record_uninstalled(modname=name, lineno=lineno)
                return

            if module_spec.origin is None:
                modname_parts_progress.append(modname_part)
                continue

            modpath = module_spec.origin

            if modpath in ("frozen", "built-in"):
                # Frozen modules are modules written in Python whose compiled
                # byte-code object is incorporated into a custom-built Python
                # interpreter by Python's freeze utility.
                # A built-in module, such as ``sys``, is compiled into the
                # interpreter.
                # Neither has an origin which names a file, so there is no
                # file to attribute to a distribution.
                continue

            modpath_path = Path(modpath)
            modname = module_spec.name

            if modname not in self._modules:
                if modpath_path.name == "__init__.py":
                    # The origin of a package is its ``__init__.py``, and we
                    # want the directory of the package itself.
                    modpath_path = modpath_path.parent
                self._modules[modname] = FoundModule(
                    modname=modname,
                    filename=modpath_path,
                )
            assert isinstance(self._location, str)
            self._modules[modname].locations.append((self._location, lineno))
            return

    def finalise(self) -> dict[str, FoundModule]:
        return self._modules

    def uninstalled(self) -> dict[str, list[tuple[str, int]]]:
        return self._uninstalled


def pyfiles(root: Path) -> Generator[Path, None, None]:
    if not root.exists():
        msg = f"source path not found: {root}"
        raise FileNotFoundError(msg)

    if root.is_file():
        if root.suffix == ".py":
            yield root.absolute()
        else:
            msg = f"{root} is not a python file or directory"
            raise ValueError(msg)
    else:
        for item in root.rglob("*.py"):
            yield item.absolute()


def validate_requirements_file(*, path: Path) -> None:
    if not path.is_file():
        msg = f"requirements file not found: {path}"
        raise FileNotFoundError(msg)


def report_input_error(
    *,
    parser: argparse.ArgumentParser,
    debug: bool,
    error: OSError | ValueError,
) -> NoReturn:
    if debug:
        raise error
    parser.error(str(error))


def log_level(*, debug: bool, verbose: bool) -> int:
    if debug:
        return logging.DEBUG
    if verbose:
        return logging.INFO
    return logging.WARNING


def source_module_names(*, paths: Iterable[Path]) -> set[str]:
    """Return the top-level module names which the scanned source provides.

    A module of the source we scan is not expected to be installed, so we
    must not report it as uninstalled. We do not import the source, so we
    take the names from the file system: any file or directory name at or
    below a path we scan can name a module of the source.
    """
    names: set[str] = set()
    for path in paths:
        absolute_path = path.absolute()
        for filename in pyfiles(path):
            names.add(filename.stem)
            if absolute_path.is_dir():
                relative_filename = filename.relative_to(absolute_path)
                names.update(relative_filename.parts[:-1])
        names.add(absolute_path.stem)
    return names


def find_imported_modules(
    *,
    paths: Iterable[Path],
    ignore_files_function: Callable[[str], bool],
    ignore_modules_function: Callable[[str], bool],
) -> ImportedModules:
    # We take the names the source provides before scanning, as an ignored
    # file still gives a module which the source, and not an installed
    # distribution, provides.
    provided_names = source_module_names(paths=paths)
    vis = _ImportVisitor(ignore_modules_function=ignore_modules_function)
    for path in paths:
        for filename in pyfiles(path):
            if ignore_files_function(str(filename)):
                log.info("ignoring: %s", filename)
                continue
            log.debug("scanning: %s", filename)
            content = filename.read_text(encoding="utf-8")
            vis.set_location(location=str(filename))
            try:
                tree = ast.parse(content, str(filename))
            except SyntaxError as exc:
                # ``ast`` knows where the problem is, but the default traceback
                # buries that behind a stack trace, so we surface it as an
                # input error with the file and line which could not be parsed.
                msg = f"could not parse {filename}:{exc.lineno}: {exc.msg}"
                raise ValueError(msg) from exc
            vis.visit(tree)

    uninstalled = {
        modname: locations
        for modname, locations in vis.uninstalled().items()
        if modname not in provided_names
    }
    return ImportedModules(found=vis.finalise(), uninstalled=uninstalled)


def installed_distribution_names() -> set[NormalizedName]:
    """Return the name of each distribution installed in the environment."""
    return {canonicalize_name(package.name) for package in get_packages_info()}


def _installed_files() -> dict[Path, str]:
    """Map each file of an installed distribution to the distribution name."""
    installed_files: dict[Path, str] = {}
    for package in get_packages_info():
        log.debug(
            "installed package: %s (at %s)",
            package.name,
            package.location,
        )
        for item in package.files or []:
            path = cached_resolve_path(path=Path(package.location) / item)
            installed_files[path] = package.name
            containing_package_path = package_path(path=path)
            if containing_package_path:
                # we've seen a package file so add the bare package directory
                # to the installed list as well as we might want to look up
                # a package by its directory path later
                installed_files[containing_package_path] = package.name
    return installed_files


@cache
def editable_source_directories() -> dict[Path, str]:
    """Map the source directory of each editable install to its distribution.

    An editable install records the files of the wheel which pip installed,
    which for an editable install are an import hook and not the modules of
    the distribution. The modules are imported from the project directory
    instead, so the files of the distribution do not tell us which modules it
    provides. The project directory is recorded in ``direct_url.json``, as
    described by PEP 610, so we take it from there.
    """
    directories: dict[Path, str] = {}
    for distribution in importlib.metadata.distributions():
        direct_url_text = distribution.read_text("direct_url.json")
        if direct_url_text is None:
            continue

        direct_url = json.loads(direct_url_text)
        directory_info = direct_url.get("dir_info", {})
        if not directory_info.get("editable", False):
            continue

        # An editable install is always of a local directory, so the URL is
        # a ``file`` URL.
        directory = cached_resolve_path(
            path=Path(url_to_path(direct_url["url"])),
        )
        directories[directory] = distribution.metadata["Name"]

    return directories


def _editable_distribution_name(
    *,
    filename: Path,
    scanned_paths: Iterable[Path],
) -> str | None:
    """Return the editable distribution which provides ``filename``.

    Return ``None`` when no editable install provides the file.

    A file of the source we scan is not a file of a dependency even when the
    source is installed as editable, as it is the project being checked and
    not a distribution it requires.
    """
    if any(
        filename == scanned_path or filename.is_relative_to(scanned_path)
        for scanned_path in scanned_paths
    ):
        return None

    for directory, name in editable_source_directories().items():
        if filename.is_relative_to(directory):
            return name
    return None


def used_packages(
    *,
    used_modules: dict[str, FoundModule],
    paths: Iterable[Path],
) -> dict[NormalizedName, list[FoundModule]]:
    """Map each distribution used by the scanned source to its uses."""
    installed_files = _installed_files()
    scanned_paths = [cached_resolve_path(path=path) for path in paths]

    used: collections.defaultdict[NormalizedName, list[FoundModule]] = (
        collections.defaultdict(list)
    )
    for modname, info in used_modules.items():
        # probably standard library if it's not in the files list
        name = installed_files.get(info.filename)
        if name is None:
            name = _editable_distribution_name(
                filename=info.filename,
                scanned_paths=scanned_paths,
            )

        if name is None:
            log.debug(
                "used module: %s (from file %s, assuming stdlib or local)",
                modname,
                info.filename,
            )
            continue

        log.debug("used module: %s (from package %s)", modname, name)
        used[canonicalize_name(name)].append(info)

    return used


def find_required_modules(
    *,
    ignore_requirements_function: Callable[
        [str | ParsedRequirement],
        bool,
    ],
    skip_incompatible: bool,
    requirements_filename: Path,
) -> set[NormalizedName]:
    explicit: set[NormalizedName] = set()
    for requirement in parse_requirements(
        str(requirements_filename),
        session=PipSession(),
    ):
        requirement_name = install_req_from_line(
            requirement.requirement,
        ).name
        if requirement_name is None:
            # A direct URL such as ``git+ssh://git@example.com/org/repo.git``
            # carries no distribution name, and pip will not learn one without
            # fetching the project. Skipping the line would silently drop a
            # requirement and report the modules it provides as missing, so
            # ask for the name instead of guessing at it.
            hint = "Add an '#egg=<name>' fragment naming the distribution."
            msg = f"requirement has no name: {requirement.requirement}. {hint}"
            raise ValueError(msg)

        if ignore_requirements_function(requirement):
            log.debug("ignoring requirement: %s", requirement_name)
            continue

        if skip_incompatible:
            requirement_string = requirement.requirement
            if not has_compatible_markers(full_requirement=requirement_string):
                log.debug(
                    "ignoring requirement (incompatible environment "
                    "marker): %s",
                    requirement_string,
                )
                continue

        log.debug("found requirement: %s", requirement_name)
        explicit.add(canonicalize_name(requirement_name))

    return explicit


def has_compatible_markers(*, full_requirement: str) -> bool:
    if ";" not in full_requirement:
        return True  # No environment marker.

    enviroment_marker = full_requirement.split(";")[1]
    if not enviroment_marker:
        return True  # Empty environment marker.

    return Marker(enviroment_marker).evaluate()


def package_path(*, path: Path) -> Path | None:
    """Return the package path for a given Python package sentinel file.

    Return None if the path is not a sentinel file.

    A sentinel file is the __init__.py or its compiled variants.
    """
    if path.parent == path.parent.parent:
        return None

    if path.name not in ("__init__.py", "__init__.pyc", "__init__.pyo"):
        return None

    return path.parent


def _null_ignorer(_: str | ParsedRequirement) -> bool:
    return False


def ignorer(*, ignore_cfg: list[str]) -> Callable[..., bool]:
    if not ignore_cfg:
        return _null_ignorer

    def ignorer_function(
        candidate: str | ParsedRequirement,
        ignore_cfg: list[str] = ignore_cfg,
    ) -> bool:
        working_directory = Path.cwd()
        for ignore in ignore_cfg:
            if isinstance(candidate, str):
                candidate_path = candidate
            else:
                optional_candidate_path = install_req_from_line(
                    candidate.requirement,
                ).name
                assert isinstance(optional_candidate_path, str)
                candidate_path = optional_candidate_path

            if fnmatch.fnmatch(candidate_path, ignore):
                return True

            # Files are given as absolute paths, while an ignore glob is
            # usually written relative to the working directory, so we match
            # against the relative path as well.
            # A path may contain ``..``, for example when the source to scan
            # was given as ``scripts/../src``, so we normalize it before
            # comparing.
            # We use ``Path`` rather than ``os.path.relpath``, which raises
            # ``ValueError`` on Windows for a path on a different drive to the
            # working directory.
            absolute_candidate = Path(
                os.path.normpath(working_directory / candidate_path),
            )
            if absolute_candidate.is_relative_to(working_directory):
                relative_candidate = absolute_candidate.relative_to(
                    working_directory,
                )
                if fnmatch.fnmatch(str(relative_candidate), ignore):
                    return True
        return False

    return ignorer_function


def _yellow(*, message: str) -> str:
    yellow = "\033[33m"
    reset = "\033[0m"
    return f"{yellow}{message}{reset}"


def wrong_environment_warning(
    *,
    running_prefix: Path,
    active_virtualenv: str | None,
    color: bool,
) -> str | None:
    """Return a warning if we do not run from the active virtual environment.

    Return ``None`` when there is nothing to warn about, which is when no
    virtual environment is active or when we run from the active one.

    A shell caches the paths of the commands it has run, so right after
    ``pip install pip-check-reqs`` in a new virtual environment, the shell
    can still resolve ``pip-missing-reqs`` to a command from another
    environment.
    That command inspects the packages installed alongside it, not the ones
    in the active environment, so the results describe the wrong environment.
    """
    if not active_virtualenv:
        return None

    active_prefix = Path(active_virtualenv).resolve()
    resolved_running_prefix = running_prefix.resolve()
    if active_prefix == resolved_running_prefix:
        return None

    message = (
        f"WARNING: Running from {resolved_running_prefix}, but the active "
        f"virtual environment is {active_prefix}. "
        "Results describe the environment pip-check-reqs is installed in. "
        "Install pip-check-reqs in the active virtual environment, and "
        'run "hash -r" ("rehash" in zsh), to check that environment.'
    )
    if color:
        return _yellow(message=message)
    return message


def report_wrong_environment(*, stream: TextIO) -> None:
    """Write a warning to ``stream`` if we run from the wrong environment."""
    warning = wrong_environment_warning(
        running_prefix=Path(sys.prefix),
        active_virtualenv=os.environ.get("VIRTUAL_ENV"),
        color=stream.isatty(),
    )
    if warning is not None:
        stream.write(warning + "\n")


def version_info() -> str:
    major, minor, patch = sys.version_info[:3]
    python_version = f"{major}.{minor}.{patch}"
    parent_directory = Path(__file__).parent.resolve()
    return (
        f"pip-check-reqs {__version__} "
        f"from {parent_directory} "
        f"(python {python_version})"
    )
