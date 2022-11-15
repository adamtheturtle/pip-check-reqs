import ast
import fnmatch
import importlib
import logging
import optparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Generator, List, Optional, Set, Tuple, Union

from packaging.markers import Marker
from packaging.utils import NormalizedName, canonicalize_name
from pip._internal.network.session import PipSession
from pip._internal.req.constructors import install_req_from_line
from pip._internal.req.req_file import ParsedRequirement, parse_requirements

from . import __version__

log = logging.getLogger(__name__)


@dataclass
class FoundModule:
    modname: str
    filename: str
    locations: List[Tuple[str, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.filename = os.path.realpath(self.filename)


class ImportVisitor(ast.NodeVisitor):
    def __init__(self, options: optparse.Values) -> None:
        super(ImportVisitor, self).__init__()
        self._options = options
        self._modules: Dict[str, FoundModule] = {}
        self._location: Optional[str] = None

    def set_location(self, location: str) -> None:
        self._location = location

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._addModule(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "__future__":
            # not an actual module
            return
        for alias in node.names:
            if node.module is None:
                # relative import
                continue
            self._addModule(node.module + "." + alias.name, node.lineno)

    def _addModule(self, modname: str, lineno: int) -> None:
        if self._options.ignore_mods(modname):
            return
        path_finder = importlib.machinery.PathFinder()
        path = None
        progress = []
        modpath = last_modpath = None
        for p in modname.split("."):
            try:
                find_spec_result = path_finder.find_spec(p, path)
            except ModuleNotFoundError:  # pragma: no cover
                # The component specified at this point is not importable.
                # At this point it is not a package (it is just an attr of a
                # package).
                #
                # This is here because of the "find_spec" docs - we should add
                # a test which hits it.
                break

            if find_spec_result is None:
                # The component specified at this point is not installed.
                break

            modpath = find_spec_result.origin

            # success! we found *something*
            progress.append(p)

            # we might have previously seen a useful path though...
            if modpath is None:  # pragma: no cover
                # the sys module will hit this code path, and os will on 3.11+.
                # possibly others will, but I've not discovered them.
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


def pyfiles(root: str) -> Generator[str, None, None]:
    root_path = Path(root)
    if root_path.is_file():
        if root_path.suffix == ".py":
            yield str(root_path.absolute())
        else:
            raise ValueError(f"{root_path} is not a python file or directory")
    elif root_path.is_dir():
        for item in root_path.rglob("*.py"):
            yield str(item.absolute())


def find_imported_modules(options: optparse.Values) -> Dict[str, FoundModule]:
    vis = ImportVisitor(options)
    for path in options.paths:
        for filename in pyfiles(path):
            if options.ignore_files(filename):
                log.info("ignoring: %s", os.path.relpath(filename))
                continue
            log.debug("scanning: %s", os.path.relpath(filename))
            with open(filename, encoding="utf-8") as f:
                content = f.read()
            vis.set_location(filename)
            vis.visit(ast.parse(content, filename))
    return vis.finalise()


def find_required_modules(
    options: optparse.Values, requirements_filename: str
) -> Set[NormalizedName]:
    explicit = set()
    for requirement in parse_requirements(
        requirements_filename, session=PipSession()
    ):
        requirement_name = install_req_from_line(
            requirement.requirement,
        ).name
        assert isinstance(requirement_name, str)

        if options.ignore_reqs(requirement):
            log.debug("ignoring requirement: %s", requirement_name)
            continue

        if options.skip_incompatible:
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
    m = re.search(r"(.+)/__init__\.py[co]?$", path)
    if m is not None:
        return m.group(1)
    return ""


def ignorer(ignore_cfg: List[str]) -> Callable[..., bool]:
    if not ignore_cfg:
        return lambda candidate: False

    def f(
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
            elif fnmatch.fnmatch(os.path.relpath(candidate_path), ignore):
                return True
        return False

    return f


def version_info() -> str:
    return "pip-check-reqs {} from {} (python {})".format(
        __version__,
        str((Path(__file__) / "..").resolve()),
        "{}.{}.{}".format(*sys.version_info),
    )
