"""Find missing requirements."""

from __future__ import annotations

import argparse
import collections
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.utils import NormalizedName, canonicalize_name

from pip_check_reqs import common

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)


def find_missing_reqs(
    requirements_filename: Path,
    paths: Iterable[Path],
    ignore_files_function: Callable[[str], bool],
    ignore_modules_function: Callable[[str], bool],
    additional_requirements_filenames: Iterable[Path] = (),
) -> list[tuple[NormalizedName, list[common.FoundModule]]]:
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    imported_modules = common.find_imported_modules(
        paths=paths,
        ignore_files_function=ignore_files_function,
        ignore_modules_function=ignore_modules_function,
    )
    used_modules = imported_modules.found

    installed_files: dict[Path, str] = {}
    packages_info = common.get_packages_info()

    for package in packages_info:
        package_name = package.name
        package_location = package.location

        log.debug(
            "installed package: %s (at %s)",
            package_name,
            package_location,
        )
        for item in package.files or []:
            path = Path(package_location) / item
            path = common.cached_resolve_path(path=path)

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

    # 4. compare with requirements
    explicit: set[NormalizedName] = set()
    for filename in [
        requirements_filename,
        *additional_requirements_filenames,
    ]:
        explicit |= common.find_required_modules(
            ignore_requirements_function=common.ignorer(ignore_cfg=[]),
            skip_incompatible=False,
            requirements_filename=filename,
        )

    _report_uninstalled_imports(
        uninstalled=imported_modules.uninstalled,
        explicit=explicit,
    )

    return [(name, used[name]) for name in used if name not in explicit]


def _report_uninstalled_imports(
    *,
    uninstalled: dict[str, list[tuple[str, int]]],
    explicit: set[NormalizedName],
) -> None:
    """Warn about imports of modules which are not installed.

    We tell which distribution provides a module from the files of the
    installed distribution, so we cannot tell whether a module which is not
    installed is required. Such an import was silently ignored, which hid
    both an import of the wrong name and a package uninstalled by mistake.
    """
    for modname, locations in uninstalled.items():
        if canonicalize_name(modname) in explicit:
            # The requirement is listed but not installed, so there is
            # nothing to report: the import is accounted for.
            continue

        for filename, lineno in locations:
            log.warning(
                "%s:%s module=%s is not installed, so we cannot tell which "
                "requirement provides it",
                filename,
                lineno,
                modname,
            )


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*")
    parser.add_argument(
        "--requirements-file",
        dest="requirements_filenames",
        metavar="PATH",
        type=Path,
        action="append",
        help=(
            "path to a requirements file; may be repeated "
            '(defaults to "requirements.txt")'
        ),
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

    requirements_filenames = parse_result.requirements_filenames or [
        Path("requirements.txt"),
    ]
    ignore_files = common.ignorer(ignore_cfg=parse_result.ignore_files)
    ignore_mods = common.ignorer(ignore_cfg=parse_result.ignore_mods)

    logging.basicConfig(format="%(message)s")
    level = common.log_level(
        debug=parse_result.debug,
        verbose=parse_result.verbose,
    )
    log.setLevel(level)
    common.log.setLevel(level)

    log.info(common.version_info())
    common.report_wrong_environment(stream=sys.stderr)

    try:
        for requirements_filename in requirements_filenames:
            common.validate_requirements_file(path=requirements_filename)
        missing = find_missing_reqs(
            requirements_filename=requirements_filenames[0],
            paths=parse_result.paths,
            ignore_files_function=ignore_files,
            ignore_modules_function=ignore_mods,
            additional_requirements_filenames=requirements_filenames[1:],
        )
    except (OSError, ValueError) as error:
        common.report_input_error(
            parser=parser,
            debug=parse_result.debug,
            error=error,
        )

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
