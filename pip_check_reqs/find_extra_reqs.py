"""Find extra requirements."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pip_check_reqs import common

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)


def find_extra_reqs(
    *,
    requirements_filename: Path,
    paths: Iterable[Path],
    ignore_files_function: Callable[[Path], bool],
    ignore_modules_function: Callable[[str], bool],
    ignore_requirements_function: Callable[[str], bool],
    skip_incompatible: bool,
    use_gitignore: bool,
) -> list[str]:
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    used_modules = common.find_imported_modules(
        paths=paths,
        ignore_files_function=ignore_files_function,
        ignore_modules_function=ignore_modules_function,
        use_gitignore=use_gitignore,
    ).found

    installed_names = common.installed_distribution_names()

    # 3. match imported modules against those packages
    used = common.used_packages(used_modules=used_modules, paths=paths)

    # 4. compare with requirements
    explicit = common.find_required_modules(
        ignore_requirements_function=ignore_requirements_function,
        skip_incompatible=skip_incompatible,
        requirements_filename=requirements_filename,
    )

    extras: list[str] = []
    for name in explicit:
        if name in used:
            continue

        if name not in installed_names:
            # We know which modules a requirement provides by looking at the
            # files of the installed distribution, so a requirement which is
            # not installed looks unused even when the code imports it.
            # Reporting it would be a false positive, so we say what we could
            # not check instead.
            log.warning(
                "%s is not installed, so we cannot tell whether it is used",
                name,
            )
            continue

        extras.append(name)

    return extras


def main(arguments: list[str] | None = None) -> None:
    """pip-extra-reqs entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*")
    parser.add_argument(
        "--requirements-file",
        dest="requirements_filename",
        type=Path,
        metavar="PATH",
        default=Path("requirements.txt"),
        help='path to the requirements file (defaults to "requirements.txt")',
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
        "-g",
        "--use-gitignore",
        dest="use_gitignore",
        action="store_true",
        default=False,
        help="skip files and directories which a .gitignore file ignores",
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
        sys.stdout.write(common.version_info() + "\n")
        sys.exit(0)

    if not parse_result.paths:
        parser.error("no source files or directories specified")

    ignore_files = common.file_ignorer(
        ignore_cfg=parse_result.ignore_files,
    )
    ignore_mods = common.ignorer(ignore_cfg=parse_result.ignore_mods)
    ignore_reqs = common.ignorer(ignore_cfg=parse_result.ignore_reqs)

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
        common.validate_requirements_file(
            path=parse_result.requirements_filename,
        )
        extras = find_extra_reqs(
            requirements_filename=parse_result.requirements_filename,
            paths=parse_result.paths,
            ignore_files_function=ignore_files,
            ignore_modules_function=ignore_mods,
            ignore_requirements_function=ignore_reqs,
            skip_incompatible=parse_result.skip_incompatible,
            use_gitignore=parse_result.use_gitignore,
        )
    except (OSError, ValueError) as error:
        common.report_input_error(
            parser=parser,
            debug=parse_result.debug,
            error=error,
        )

    if extras:
        log.warning("Extra requirements:")
    for name in extras:
        message = f"{name} in {parse_result.requirements_filename}"
        log.warning(message)

    if extras:
        sys.exit(1)
