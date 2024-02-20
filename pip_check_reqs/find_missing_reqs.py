"""Find missing requirements."""

from __future__ import annotations

import argparse
import collections
import datetime
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from packaging.utils import NormalizedName, canonicalize_name
from pip._internal.network.session import PipSession
from pip._internal.req.constructors import install_req_from_line
from pip._internal.req.req_file import parse_requirements

from pip_check_reqs import common

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pip_check_reqs.common import (
        FoundModule,
    )

log = logging.getLogger(__name__)

MICROSECONDS_IN_SECOND = 1000000


def find_missing_reqs(
    requirements_filename: Path,
    paths: Iterable[Path],
    ignore_files_function: Callable[[str], bool],
    ignore_modules_function: Callable[[str], bool],
) -> list[tuple[NormalizedName, list[FoundModule]]]:
    start = datetime.datetime.now(tz=datetime.timezone.utc)
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    used_modules = common.find_imported_modules(
        paths=paths,
        ignore_files_function=ignore_files_function,
        ignore_modules_function=ignore_modules_function,
    )

    after_find_imported_modules = datetime.datetime.now(tz=datetime.timezone.utc)

    # 2. find which packages provide which files
    installed_files = {}

    after_all_pkgs = datetime.datetime.now(tz=datetime.timezone.utc)

    packages_info = common.get_packages_info()

    after_search_packages_info = datetime.datetime.now(tz=datetime.timezone.utc)

    here = Path().resolve()

    for package in packages_info:
        package_name = package.name
        package_location = package.location
        package_files: list[str] = []
        for item in package.files or []:
            item_location_rel = Path(package_location) / item
            item_location = common.cached_resolve_path(path=item_location_rel)
            if item_location.is_relative_to(here):
                relative_item_location = item_location.relative_to(here)
            else:
                relative_item_location = item_location
            package_files.append(str(relative_item_location))

        log.debug(
            "installed package: %s (at %s)",
            package_name,
            package_location,
        )
        for package_file in package_files:
            path = Path(package_location) / package_file
            path = common.cached_resolve_path(path=path)

            installed_files[path] = package_name
            package_path = common.package_path(path=path)
            if package_path:
                # we've seen a package file so add the bare package directory
                # to the installed list as well as we might want to look up
                # a package by its directory path later
                installed_files[package_path] = package_name

    after_loop_packages_info = datetime.datetime.now(tz=datetime.timezone.utc)


    # 3. match imported modules against those packages
    used: collections.defaultdict[
        NormalizedName,
        list[common.FoundModule],
    ] = collections.defaultdict(list)
    for modname, info in used_modules.items():
        # probably standard library if it's not in the files list
        if info.filename in installed_files:
            used_name = canonicalize_name(name=installed_files[info.filename])
            log.debug(
                "used module: %s (from package %s)",
                modname,
                installed_files[info.filename],
            )
            used[used_name].append(info)
        else:
            log.debug(
                "used module: %s (from file %s, assuming stdlib or local)",
                modname,
                info.filename,
            )

    after_match_used = datetime.datetime.now(tz=datetime.timezone.utc)

    # 4. compare with requirements
    explicit: set[NormalizedName] = set()
    for requirement in parse_requirements(
        str(requirements_filename),
        session=PipSession(),
    ):
        requirement_name = install_req_from_line(
            requirement.requirement,
        ).name

        assert isinstance(requirement_name, str)
        log.debug("found requirement: %s", requirement_name)
        explicit.add(canonicalize_name(requirement_name))

    after_set_explicit = datetime.datetime.now(tz=datetime.timezone.utc)

    after_find_imported_modules - start
    after_all_pkgs - after_find_imported_modules
    after_search_packages_info - after_all_pkgs
    after_loop_packages_info - after_search_packages_info
    after_match_used - after_loop_packages_info
    after_set_explicit - after_match_used
    return [(name, used[name]) for name in used if name not in explicit]


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*")
    parser.add_argument(
        "--requirements-file",
        dest="requirements_filename",
        metavar="PATH",
        type=Path,
        default="requirements.txt",
        help="path to the requirements file "
        '(defaults to "requirements.txt")',
    )
    parser.add_argument(
        "-f",
        "--ignore-file",
        dest="ignore_files",
        action="append",
        default=[],
        help="file paths globs to ignore",
    )
    parser.add_argument(
        "-m",
        "--ignore-module",
        dest="ignore_mods",
        action="append",
        default=[],
        help="used module names (globs are ok) to ignore",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="be more verbose",
    )
    parser.add_argument(
        "-d",
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="be *really* verbose",
    )
    parser.add_argument(
        "-V",
        "--version",
        dest="version",
        action="store_true",
        default=False,
        help="display version information",
    )

    parse_result = parser.parse_args(arguments)

    if parse_result.version:
        sys.stdout.write(common.version_info() + "\n")
        sys.exit(0)

    if not parse_result.paths:
        parser.error("no source files or directories specified")

    ignore_files = common.ignorer(ignore_cfg=parse_result.ignore_files)
    ignore_mods = common.ignorer(ignore_cfg=parse_result.ignore_mods)

    logging.basicConfig(format="%(message)s")
    if parse_result.debug:
        level = logging.DEBUG
    elif parse_result.verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    log.setLevel(level)
    common.log.setLevel(level)

    log.info(common.version_info())

    before_find_missing_reqs = datetime.datetime.now(tz=datetime.timezone.utc)
    missing = find_missing_reqs(
        requirements_filename=parse_result.requirements_filename,
        paths=parse_result.paths,
        ignore_files_function=ignore_files,
        ignore_modules_function=ignore_mods,
    )

    after_find_missing_reqs = datetime.datetime.now(tz=datetime.timezone.utc)

    after_find_missing_reqs - before_find_missing_reqs

    if missing:
        log.warning("Missing requirements:")
    for name, uses in missing:
        for use in uses:
            for filename, lineno in use.locations:
                log.warning(
                    "%s:%s dist=%s module=%s",
                    filename,
                    lineno,
                    name,
                    use.modname,
                )

    if missing:
        sys.exit(1)

if __name__ == "__main__":
    main()
