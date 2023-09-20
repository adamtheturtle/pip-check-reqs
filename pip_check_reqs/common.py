"""Common functions."""

from __future__ import annotations

import ast
import fnmatch
import logging
import os
import sys
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import (
    Callable,
    Generator,
    Iterable,
)

from packaging.markers import Marker
from packaging.utils import NormalizedName, canonicalize_name
from pip._internal.network.session import PipSession
from pip._internal.req.constructors import install_req_from_line
from pip._internal.req.req_file import ParsedRequirement, parse_requirements

from . import __version__

log = logging.getLogger(__name__)


@dataclass
class FoundModule:
    """A module with uses in the source."""

    modname: str
    filename: Path
    locations: list[tuple[str, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.filename = Path(self.filename).resolve()


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, ignore_modules_function: Callable[[str], bool]) -> None:
        super().__init__()
        self._ignore_modules_function = ignore_modules_function
        self._modules: dict[str, FoundModule] = {}
        self._location: str | None = None

    def set_location(self, *, location: str) -> None:
        self._location = location

    # Ignore the name error as we are overriding the method.
    def visit_Import(  # noqa: N802, pylint: disable=invalid-name
        self,
        node: ast.Import,
    ) -> None:
        for alias in node.names:
            self._add_module(alias.name, node.lineno)

    # Ignore the name error as we are overriding the method.
    def visit_ImportFrom(  # noqa: N802, pylint: disable=invalid-name
        self,
        node: ast.ImportFrom,
    ) -> None:
        if node.module == "__future__":
            # not an actual module
            return
        for alias in node.names:
            if node.module is None or node.level != 0:
                # relative import
                continue
            self._add_module(node.module + "." + alias.name, node.lineno)

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
                return

            if module_spec.origin is None:
                modname_parts_progress.append(modname_part)
                continue

            modpath = module_spec.origin

            if modpath == "frozen":
                # Frozen modules are modules written in Python whose compiled
                # byte-code object is incorporated into a custom-built Python
                # interpreter by Python's freeze utility.
                continue

            modpath_path = Path(modpath)
            modname = module_spec.name

            if modname not in self._modules:
                if modpath_path.is_file():
                    if modpath_path.name == "__init__.py":
                        modpath_path = modpath_path.parent
                    else:
                        # We have this empty "else" so that we are
                        # not tempted to combine the "is file" and "is
                        # __init__" checks, and to make sure we have coverage
                        # for this case.
                        pass
                self._modules[modname] = FoundModule(
                    modname=modname,
                    filename=modpath_path,
                )
            assert isinstance(self._location, str)
            self._modules[modname].locations.append((self._location, lineno))
            return

    def finalise(self) -> dict[str, FoundModule]:
        return self._modules


def pyfiles(root: Path) -> Generator[Path, None, None]:
    if root.is_file():
        if root.suffix == ".py":
            yield root.absolute()
        else:
            msg = f"{root} is not a python file or directory"
            raise ValueError(msg)
    else:
        for item in root.rglob("*.py"):
            yield item.absolute()


def find_imported_modules(
    *,
    paths: Iterable[Path],
    ignore_files_function: Callable[[str], bool],
    ignore_modules_function: Callable[[str], bool],
) -> dict[str, FoundModule]:
    vis = _ImportVisitor(ignore_modules_function=ignore_modules_function)
    for path in paths:
        for filename in pyfiles(path):
            if ignore_files_function(str(filename)):
                log.info("ignoring: %s", filename)
                continue
            log.debug("scanning: %s", filename)
            content = filename.read_text(encoding="utf-8")
            vis.set_location(location=str(filename))
            vis.visit(ast.parse(content, str(filename)))
    return vis.finalise()


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
        assert isinstance(requirement_name, str)

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


def ignorer(*, ignore_cfg: list[str]) -> Callable[..., bool]:
    if not ignore_cfg:
        return lambda _: False

    def ignorer_function(
        candidate: str | ParsedRequirement,
        ignore_cfg: list[str] = ignore_cfg,
    ) -> bool:
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
            if fnmatch.fnmatch(os.path.relpath(candidate_path), ignore):
                return True
        return False

    return ignorer_function


def version_info() -> str:
    major, minor, patch = sys.version_info[:3]
    python_version = f"{major}.{minor}.{patch}"
    parent_directory = Path(__file__).parent.resolve()
    return (
        f"pip-check-reqs {__version__} "
        f"from {parent_directory} "
        f"(python {python_version})"
    )
