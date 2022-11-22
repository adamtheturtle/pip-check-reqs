"""Common functions."""

import ast
import fnmatch
import imp
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Callable,
    Dict,
    Generator,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Union,
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
    filename: str
    locations: List[Tuple[str, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.filename = os.path.realpath(self.filename)


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, ignore_modules_function: Callable[[str], bool]) -> None:
        super().__init__()
        self._ignore_modules_function = ignore_modules_function
        self._modules: Dict[str, FoundModule] = {}
        self._location: Optional[str] = None

    def set_location(self, location: str) -> None:
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
        for alias in node.names:
            if node.module is None or node.level != 0:
                # relative import
                continue
            self._add_module(node.module + "." + alias.name, node.lineno)

    def _add_module(self, modname: str, lineno: int) -> None:
        if self._ignore_modules_function(modname):
            return
        path = None
        progress = []
        modpath = last_modpath = None
        for modname_part in modname.split("."):
            try:
                _, modpath, _ = imp.find_module(modname_part, path)
            except ImportError:
                # the component specified at this point is not importable
                # (is just an attribute of the module)
                # *or* it's not actually installed, so we don't care either
                break

            # success! we found *something*
            progress.append(modname_part)

            # we might have previously seen a useful path though...
            if modpath is None:
                # the `sys` module will hit this code path, and `os` will on
                # 3.11+.
                # Possibly others will, but I've not discovered them.
                modpath = last_modpath
                break

            # ... though it might not be a file, so not interesting to us
            if not os.path.isdir(modpath):
                break

            path = [modpath]
            last_modpath = modpath

        if modpath is None:
            # the module doesn't actually appear to exist on disk
            return

        modname = ".".join(progress)
        if modname not in self._modules:
            self._modules[modname] = FoundModule(modname, modpath)
        assert isinstance(self._location, str)
        self._modules[modname].locations.append((self._location, lineno))

    def finalise(self) -> Dict[str, FoundModule]:
        result = self._modules
        return result


def pyfiles(root: Path) -> Generator[Path, None, None]:
    if root.is_file():
        if root.suffix == ".py":
            yield root.absolute()
        else:
            raise ValueError(f"{root} is not a python file or directory")
    elif root.is_dir():
        for item in root.rglob("*.py"):
            yield item.absolute()


def find_imported_modules(
    paths: Iterable[Path],
    ignore_files_function: Callable[[str], bool],
    ignore_modules_function: Callable[[str], bool],
) -> Dict[str, FoundModule]:
    vis = _ImportVisitor(ignore_modules_function=ignore_modules_function)
    for path in paths:
        for filename in pyfiles(path):
            if ignore_files_function(str(filename)):
                log.info("ignoring: %s", os.path.relpath(filename))
                continue
            log.debug("scanning: %s", os.path.relpath(filename))
            with open(filename, encoding="utf-8") as file_obj:
                content = file_obj.read()
            vis.set_location(str(filename))
            vis.visit(ast.parse(content, str(filename)))
    return vis.finalise()


def find_required_modules(
    ignore_requirements_function: Callable[
        [Union[str, ParsedRequirement]], bool
    ],
    skip_incompatible: bool,
    requirements_filename: Path,
) -> Set[NormalizedName]:
    explicit = set()
    for requirement in parse_requirements(
        str(requirements_filename), session=PipSession()
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
            if not has_compatible_markers(requirement_string):
                log.debug(
                    "ignoring requirement (incompatible environment "
                    "marker): %s",
                    requirement_string,
                )
                continue

        log.debug("found requirement: %s", requirement_name)
        explicit.add(canonicalize_name(requirement_name))

    return explicit


def has_compatible_markers(full_requirement: str) -> bool:
    if ";" not in full_requirement:
        return True  # No environment marker.

    enviroment_marker = full_requirement.split(";")[1]
    if not enviroment_marker:
        return True  # Empty environment marker.

    return Marker(enviroment_marker).evaluate()


def is_package_file(path: str) -> str:
    """Determines whether the path points to a Python package sentinel
    file - the __init__.py or its compiled variants.
    """
    search_result = re.search(r"(.+)/__init__\.py[co]?$", path)
    if search_result is not None:
        return search_result.group(1)
    return ""


def ignorer(ignore_cfg: List[str]) -> Callable[..., bool]:
    if not ignore_cfg:
        return lambda candidate: False

    def ignorer_function(
        candidate: Union[str, ParsedRequirement],
        ignore_cfg: List[str] = ignore_cfg,
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
