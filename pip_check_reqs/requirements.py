"""Reading the requirements a project declares."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from pip._internal.exceptions import InstallationError
from pip._internal.network.session import PipSession
from pip._internal.req.constructors import install_req_from_line
from pip._internal.req.req_file import parse_requirements
from pip._internal.utils.compat import tomllib
from pip._internal.utils.urls import url_to_path
from pip._internal.vcs.versioncontrol import vcs

from .common import cached_resolve_path, direct_urls

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from pip._internal.models.link import Link
    from pip._internal.req.req_file import ParsedRequirement
    from pip._internal.req.req_install import InstallRequirement

log = logging.getLogger(__name__)


def validate_requirements_file(*, path: Path) -> None:
    if not path.is_file():
        msg = f"requirements file not found: {path}"
        raise FileNotFoundError(msg)


def _direct_url_key(
    *,
    url: str,
    vcs_name: str | None,
    subdirectory: str | None,
) -> str:
    """Return a key which identifies the project a direct URL points at.

    A local directory may be written as a relative path in one place and as
    an absolute ``file`` URL in another, so it is keyed by its resolved path.
    A version control URL is keyed with the name of the version control
    system, as ``git+https://...`` is written in a requirements file.
    A repository may hold several projects, each in its own subdirectory, so
    the subdirectory is part of the key.
    """
    if vcs_name is not None:
        key = f"{vcs_name}+{url}"
    elif url.startswith("file:"):
        key = str(cached_resolve_path(path=Path(url_to_path(url))))
    else:
        key = url

    if subdirectory is not None:
        key = f"{key}#subdirectory={subdirectory}"
    return key


@cache
def direct_url_distribution_names() -> dict[str, str]:
    """Map the direct URL each distribution was installed from to its name.

    The keys are as ``_direct_url_key`` gives them.
    """
    names: dict[str, str] = {}
    for name, direct_url in direct_urls():
        vcs_info = direct_url.get("vcs_info")
        vcs_name = vcs_info["vcs"] if vcs_info is not None else None
        key = _direct_url_key(
            url=direct_url["url"],
            vcs_name=vcs_name,
            subdirectory=direct_url.get("subdirectory"),
        )
        names[key] = name
    return names


def _link_key(*, link: Link) -> str:
    """Return the ``_direct_url_key`` of the project a requirement points at.

    A requirement may pin a revision, as ``git+https://...@v1.0`` does, and
    may carry an ``#egg=`` fragment. Neither is recorded in the install, so
    both are left out of the key.
    """
    if link.is_vcs:
        backend = vcs.get_backend_for_scheme(link.scheme)
        assert backend is not None
        url, _revision, _auth = backend.get_url_rev_and_auth(
            link.url_without_fragment,
        )
        return _direct_url_key(
            url=url,
            vcs_name=backend.name,
            subdirectory=link.subdirectory_fragment,
        )
    return _direct_url_key(
        url=link.url_without_fragment,
        vcs_name=None,
        subdirectory=link.subdirectory_fragment,
    )


def _install_requirement(
    *,
    requirement: ParsedRequirement,
) -> InstallRequirement:
    """Return pip's reading of a requirement line.

    pip splits the line into the name, the version specifiers, the URL and
    the environment marker, so we do not parse the line ourselves.
    """
    try:
        return install_req_from_line(requirement.requirement)
    except InstallationError as exc:
        # pip describes the problem over several lines, with a caret under
        # the part of the line it could not read. We report the requirement
        # as an input error, so we keep only the first line of the reason.
        reason = str(exc).splitlines()[0]
        msg = f"could not parse requirement: {reason}"
        raise ValueError(msg) from exc


def _requirement_name(
    *,
    install_requirement: InstallRequirement,
) -> str | None:
    """Return the name of the distribution a requirement asks for.

    Return ``None`` when the name cannot be told from the line and the
    requirement is not installed.

    A direct URL such as ``git+ssh://git@example.com/org/repo.git`` or a
    local directory such as ``-e .`` carries no distribution name, and pip
    will not learn one without fetching or building the project. When such a
    requirement is installed, the install records the URL it came from, so
    we take the name from the install.
    """
    if install_requirement.name is not None:
        return install_requirement.name

    # A requirement with no name is a URL or a path, so it has a link.
    link = install_requirement.link
    assert link is not None
    return direct_url_distribution_names().get(_link_key(link=link))


@dataclass(frozen=True)
class RequirementSpec:
    """One requirement a project declares.

    A requirement comes from a line of a requirements file, or from the
    ``dependencies`` list of a ``pyproject.toml`` file. Keeping it as a plain
    record lets each source give requirements in the same form.
    """

    #: The distribution the requirement asks for.
    name: str
    #: The environment marker, or ``None`` when the requirement applies
    #: everywhere.
    marker: Marker | None
    #: The requirement as the project wrote it, for messages.
    text: str


def requirements_file_specs(*, path: Path) -> Iterator[RequirementSpec]:
    """Yield each requirement in a requirements file.

    Raise ``ValueError`` for a requirement which cannot be read, or whose
    name cannot be told.
    """
    for requirement in parse_requirements(str(path), session=PipSession()):
        install_requirement = _install_requirement(requirement=requirement)
        requirement_name = _requirement_name(
            install_requirement=install_requirement,
        )
        if requirement_name is None:
            # Skipping the line would silently drop a requirement and report
            # the modules it provides as missing, so ask for the name instead
            # of guessing at it.
            hint = (
                "Install it, or add an '#egg=<name>' fragment naming the "
                "distribution."
            )
            msg = f"requirement has no name: {requirement.requirement}. {hint}"
            raise ValueError(msg)

        # pip gives a marker from its own copy of ``packaging``. The
        # record holds the public one, so a reader which does not go through
        # pip can give the same type.
        markers = install_requirement.markers
        yield RequirementSpec(
            name=requirement_name,
            marker=None if markers is None else Marker(str(markers)),
            text=requirement.requirement,
        )


def pyproject_specs(*, path: Path) -> Iterator[RequirementSpec]:
    """Yield each ``[project]`` dependency in a ``pyproject.toml`` file.

    Only the ``dependencies`` list is read. A file with no ``[project]``
    table, or one with no ``dependencies`` list, gives no requirements.

    Raise ``ValueError`` for a requirement which cannot be parsed.
    """
    with path.open(mode="rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    # ``tomllib`` gives ``dict[str, Any]``, so the values it holds have no
    # type. ``Requirement`` rejects anything which is not a requirement
    # string.
    project_table = pyproject.get("project", {})
    for text in project_table.get("dependencies", []):
        requirement = Requirement(text)
        yield RequirementSpec(
            name=requirement.name,
            marker=requirement.marker,
            text=text,
        )


def requirement_specs(*, path: Path) -> Iterator[RequirementSpec]:
    """Yield each requirement a file declares.

    A file named ``pyproject.toml`` is read as a project file, and any other
    file as a requirements file.
    """
    if path.name == "pyproject.toml":
        return pyproject_specs(path=path)
    return requirements_file_specs(path=path)


def find_required_modules(
    *,
    ignore_requirements_function: Callable[[str], bool],
    skip_incompatible: bool,
    specs: Iterable[RequirementSpec],
) -> set[NormalizedName]:
    """Return the normalized names of the requirements which apply.

    The requirements are given as records rather than as a file, so any
    source which yields ``RequirementSpec`` records can be filtered here.
    """
    explicit: set[NormalizedName] = set()
    for spec in specs:
        if ignore_requirements_function(spec.name):
            log.debug("ignoring requirement: %s", spec.name)
            continue

        # A requirement with no environment marker applies everywhere.
        if (
            skip_incompatible
            and spec.marker is not None
            and not spec.marker.evaluate()
        ):
            log.debug(
                "ignoring requirement (incompatible environment marker): %s",
                spec.text,
            )
            continue

        log.debug("found requirement: %s", spec.name)
        explicit.add(canonicalize_name(spec.name))

    return explicit
