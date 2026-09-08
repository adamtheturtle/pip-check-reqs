"""Find missing requirements."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.utils import NormalizedName, canonicalize_name

from pip_check_reqs import common

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)


@dataclass
class MissingRequirements:
    """The requirements which no requirements file lists."""

    used: list[tuple[NormalizedName, list[common.FoundModule]]]
    """Distributions the source imports, each with the modules it imports."""

    transitive: dict[NormalizedName, set[NormalizedName]] = field(
        default_factory=dict[NormalizedName, set[NormalizedName]],
    )
    """Dependencies of the used distributions, each with the distributions
    which require it.

    This is only filled when transitive dependencies are checked.
    """


def find_missing_reqs(
    requirements_filename: Path,
    paths: Iterable[Path],
    ignore_files_function: Callable[[Path], bool],
    ignore_modules_function: Callable[[str], bool],
    additional_requirements_filenames: Iterable[Path] = (),
    *,
    transitive: bool = False,
) -> MissingRequirements:
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    imported_modules = common.find_imported_modules(
        paths=paths,
        ignore_files_function=ignore_files_function,
        ignore_modules_function=ignore_modules_function,
    )
    used_modules = imported_modules.found

    # 3. match imported modules against those packages
    used = common.used_packages(used_modules=used_modules, paths=paths)

    # 4. compare with requirements
    explicit: set[NormalizedName] = set()
    for filename in [
        requirements_filename,
        *additional_requirements_filenames,
    ]:
        explicit |= common.find_required_modules(
            ignore_requirements_function=common.ignorer(ignore_cfg=[]),
            skip_incompatible=False,
            specs=common.requirements_file_specs(path=filename),
        )

    _report_uninstalled_imports(
        uninstalled=imported_modules.uninstalled,
        explicit=explicit,
    )

    missing = MissingRequirements(
        used=[(name, used[name]) for name in used if name not in explicit],
    )
    if not transitive:
        return missing

    # A used distribution is reported with the imports which use it, so we
    # do not report it a second time as a dependency of another.
    missing.transitive = {
        name: required_by
        for name, required_by in common.transitive_dependencies(
            names=used,
        ).items()
        if name not in explicit and name not in used
    }
    return missing


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


def _report_missing(*, missing: MissingRequirements) -> None:
    """Warn about each requirement which no requirements file lists."""
    log.warning("Missing requirements:")
    for name, uses in missing.used:
        for use in uses:
            for filename, lineno in use.locations:
                log.warning(
                    "%s:%s dist=%s module=%s",
                    filename,
                    lineno,
                    name,
                    use.modname,
                )
    for name, required_by in sorted(missing.transitive.items()):
        log.warning(
            "dist=%s required by %s",
            name,
            ", ".join(sorted(required_by)),
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
        "-t",
        "--transitive",
        dest="transitive",
        action="store_true",
        default=False,
        help=(
            "also report the dependencies of the used distributions, "
            "recursively, which are not listed"
        ),
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
    ignore_files = common.file_ignorer(
        ignore_cfg=parse_result.ignore_files,
    )
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
            transitive=parse_result.transitive,
        )
    except (OSError, ValueError) as error:
        common.report_input_error(
            parser=parser,
            debug=parse_result.debug,
            error=error,
        )

    if missing.used or missing.transitive:
        _report_missing(missing=missing)
        sys.exit(1)
