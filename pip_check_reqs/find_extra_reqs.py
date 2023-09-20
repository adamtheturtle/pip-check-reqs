"""Find extra requirements."""

from __future__ import annotations

import argparse
import collections
import importlib.metadata
import logging
import os
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable
from unittest import mock

from packaging.utils import NormalizedName, canonicalize_name
from pip._internal.commands.show import (
    _PackageInfo,  # pyright: ignore[reportPrivateUsage]
    search_packages_info,
)

from pip_check_reqs import common
from pip_check_reqs.common import version_info

if TYPE_CHECKING:
    from pip._internal.req.req_file import ParsedRequirement

log = logging.getLogger(__name__)


# This is a slow operation.
# It only happens once when calling the CLI, but it is hit many times in
# tests.
# We cache the result to speed up tests.
@cache
def get_packages_info() -> list[_PackageInfo]:
    all_pkgs = [
        dist.metadata["Name"] for dist in importlib.metadata.distributions()
    ]

    # On Python 3.11 (and maybe higher), setting this environment variable
    # dramatically improves speeds.
    # See https://github.com/r1chardj0n3s/pip-check-reqs/issues/123.
    with mock.patch.dict(os.environ, {"_PIP_USE_IMPORTLIB_METADATA": "False"}):
        return list(search_packages_info(query=all_pkgs))


def find_extra_reqs(
    *,
    requirements_filename: Path,
    paths: Iterable[Path],
    ignore_files_function: Callable[[str], bool],
    ignore_modules_function: Callable[[str], bool],
    ignore_requirements_function: Callable[
        [str | ParsedRequirement],
        bool,
    ],
    skip_incompatible: bool,
) -> list[str]:
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    used_modules = common.find_imported_modules(
        paths=paths,
        ignore_files_function=ignore_files_function,
        ignore_modules_function=ignore_modules_function,
    )

    installed_files: dict[Path, str] = {}
    packages_info = get_packages_info()
    here = Path().resolve()

    for package in packages_info:
        package_name = package.name
        package_location = package.location
        package_files: list[str] = []
        for item in package.files or []:
            item_location_rel = Path(package_location) / item
            item_location = item_location_rel.resolve()
            try:
                relative_item_location = item_location.relative_to(here)
            except ValueError:
                # Ideally we would use Pathlib.is_relative_to rather than
                # checking for a ValueError, but that is only available in
                # Python 3.9+.
                relative_item_location = item_location
            package_files.append(str(relative_item_location))

        log.debug(
            "installed package: %s (at %s)",
            package_name,
            package_location,
        )
        for package_file in package_files:
            path = Path(package_location) / package_file
            path = path.resolve()

            installed_files[path] = package_name
            package_path = common.package_path(path=path)
            if package_path:
                # we've seen a package file so add the bare package directory
                # to the installed list as well as we might want to look up
                # a package by its directory path later
                installed_files[package_path] = package_name

    # 3. match imported modules against those packages
    used: collections.defaultdict[
        NormalizedName,
        list[common.FoundModule],
    ] = collections.defaultdict(list)

    for modname, info in used_modules.items():
        # probably standard library if it's not in the files list
        if info.filename in installed_files:
            used_name = canonicalize_name(installed_files[info.filename])
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

    # 4. compare with requirements
    explicit = common.find_required_modules(
        ignore_requirements_function=ignore_requirements_function,
        skip_incompatible=skip_incompatible,
        requirements_filename=requirements_filename,
    )

    return [name for name in explicit if name not in used]


def main(arguments: list[str] | None = None) -> None:
    """pip-extra-reqs entry point."""
    usage = "usage: %prog [options] files or directories"
    parser = argparse.ArgumentParser(usage)
    parser.add_argument("paths", type=Path, nargs="*")
    parser.add_argument(
        "--requirements-file",
        dest="requirements_filename",
        type=Path,
        metavar="PATH",
        default=Path("requirements.txt"),
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
        "-r",
        "--ignore-requirement",
        dest="ignore_reqs",
        action="append",
        default=[],
        help="reqs in requirements to ignore",
    )
    parser.add_argument(
        "-s",
        "--skip-incompatible",
        dest="skip_incompatible",
        action="store_true",
        default=False,
        help="skip requirements that have incompatible environment markers",
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
        sys.stdout.write(version_info() + "\n")
        sys.exit(0)

    if not parse_result.paths:
        parser.error("no source files or directories specified")

    ignore_files = common.ignorer(ignore_cfg=parse_result.ignore_files)
    ignore_mods = common.ignorer(ignore_cfg=parse_result.ignore_mods)
    ignore_reqs = common.ignorer(ignore_cfg=parse_result.ignore_reqs)

    logging.basicConfig(format="%(message)s")
    if parse_result.debug:
        level = logging.DEBUG
    elif parse_result.verbose:
        level = logging.INFO
    else:
        level = logging.WARN
    log.setLevel(level)
    common.log.setLevel(level)

    log.info(version_info())

    extras = find_extra_reqs(
        requirements_filename=parse_result.requirements_filename,
        paths=parse_result.paths,
        ignore_files_function=ignore_files,
        ignore_modules_function=ignore_mods,
        ignore_requirements_function=ignore_reqs,
        skip_incompatible=parse_result.skip_incompatible,
    )

    if extras:
        log.warning("Extra requirements:")
    for name in extras:
        message = f"{name} in {parse_result.requirements_filename}"
        log.warning(message)

    if extras:
        sys.exit(1)
