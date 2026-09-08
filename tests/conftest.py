"""Fixtures shared between test modules."""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pip_check_reqs import common

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

# On Python 3.10, pip reads the environment through ``pkg_resources``, whose
# working set is a snapshot taken when it was first imported. A distribution
# which a test installs is added to ``sys.path`` after that, so pip does not
# see it. Ask pip for the ``importlib.metadata`` backend, which reads
# ``sys.path`` as it is when it is asked. Python 3.14 uses that backend
# already, and pip removes the other one in version 26.3.
os.environ["_PIP_USE_IMPORTLIB_METADATA"] = "1"


@dataclass(frozen=True)
class EditableInstall:
    """A distribution installed in editable mode."""

    distribution_name: str
    module_name: str
    source_directory: Path
    """The directory of the project, which the modules are imported from."""


def write_dist_info(
    *,
    site_packages: Path,
    distribution_name: str,
    direct_url: dict[str, object] | None,
    requires: Iterable[str] = (),
) -> None:
    """Write the ``.dist-info`` directory of an installed distribution.

    ``requires`` gives the dependencies as ``Requires-Dist`` lines.
    """
    # A ``.dist-info`` directory is named after the normalized distribution
    # name, in which a hyphen is written as an underscore.
    normalized_name = distribution_name.replace("-", "_")
    dist_info = site_packages / f"{normalized_name}-1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "INSTALLER").write_text("pip\n", encoding="utf-8")
    requires_dist = "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requires
    )
    (dist_info / "METADATA").write_text(
        textwrap.dedent(
            f"""\
            Metadata-Version: 2.1
            Name: {distribution_name}
            Version: 1.0
            """,
        )
        + requires_dist,
        encoding="utf-8",
    )
    # An editable install records the import hook which pip installed, and
    # not the modules of the distribution.
    (dist_info / "RECORD").write_text(
        f"{dist_info.name}/METADATA,,\n",
        encoding="utf-8",
    )
    if direct_url is not None:
        (dist_info / "direct_url.json").write_text(
            json.dumps(direct_url),
            encoding="utf-8",
        )


@pytest.fixture
def editable_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[EditableInstall]:
    """Install a distribution in editable mode, as ``pip install -e`` does.

    An editable install imports its modules from the project directory, which
    is on ``sys.path``, rather than from a copy in ``site-packages``. The
    ``.dist-info`` directory of the install records the project directory in
    ``direct_url.json``, as described by PEP 610.
    """
    distribution_name = "editable-package-12345"
    module_name = "editable_package_12345"

    source_directory = tmp_path / "editable-project"
    package_directory = source_directory / module_name
    package_directory.mkdir(parents=True)
    (package_directory / "__init__.py").touch()
    # pip only accepts a directory as a requirement when it is a project, so
    # the directory must have a ``pyproject.toml`` to be written in a
    # requirements file.
    (source_directory / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "{distribution_name}"
            version = "1.0"
            """,
        ),
        encoding="utf-8",
    )

    site_packages = tmp_path / "editable-site-packages"
    write_dist_info(
        site_packages=site_packages,
        distribution_name=distribution_name,
        direct_url={
            "url": source_directory.as_uri(),
            "dir_info": {"editable": True},
        },
    )

    # The parameter has no annotation until
    # https://github.com/pytest-dev/pytest/pull/14988 is released.
    monkeypatch.syspath_prepend(  # pyright: ignore[reportUnknownMemberType]
        str(source_directory),
    )
    # The parameter has no annotation until
    # https://github.com/pytest-dev/pytest/pull/14988 is released.
    monkeypatch.syspath_prepend(  # pyright: ignore[reportUnknownMemberType]
        str(site_packages),
    )

    common.get_packages_info.cache_clear()
    common.editable_source_directories.cache_clear()
    common.direct_url_distribution_names.cache_clear()

    yield EditableInstall(
        distribution_name=distribution_name,
        module_name=module_name,
        source_directory=source_directory,
    )

    # The distribution goes away with the temporary directory, so the caches
    # must not describe it for the tests which follow.
    common.get_packages_info.cache_clear()
    common.editable_source_directories.cache_clear()
    common.direct_url_distribution_names.cache_clear()


@dataclass(frozen=True)
class DependencyChain:
    """Installed distributions which depend on one another.

    The source imports ``top``, which requires ``middle``, which requires
    the ``fast`` extra of ``bottom`` and a distribution which is not
    installed. ``bottom`` requires ``top`` in turn, so the chain has a cycle.
    """

    top: str
    top_module: str
    middle: str
    bottom: str
    fast: str
    """A dependency of the ``fast`` extra of ``bottom``."""
    uninstalled: str
    """A dependency of ``middle`` which is not installed."""
    unasked_extra: str
    """A dependency of an extra of ``top`` which nothing asks for."""
    incompatible: str
    """A dependency of ``top`` whose environment marker does not hold."""


@pytest.fixture
def dependency_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[DependencyChain]:
    """Install distributions which depend on one another."""
    chain = DependencyChain(
        top="top-package-12345",
        top_module="top_package_12345",
        middle="middle-package-12345",
        bottom="bottom-package-12345",
        fast="fast-package-12345",
        uninstalled="uninstalled-package-12345",
        unasked_extra="unasked-extra-package-12345",
        incompatible="incompatible-package-12345",
    )
    site_packages = tmp_path / "chain-site-packages"

    requires = {
        chain.top: [
            chain.middle,
            f'{chain.unasked_extra}; extra == "socks"',
            f'{chain.incompatible}; python_version < "3"',
        ],
        chain.middle: [f"{chain.bottom}[fast]", chain.uninstalled],
        chain.bottom: [f'{chain.fast}; extra == "fast"', chain.top],
        chain.fast: [],
        chain.unasked_extra: [],
        chain.incompatible: [],
    }
    for distribution_name, distribution_requires in requires.items():
        write_dist_info(
            site_packages=site_packages,
            distribution_name=distribution_name,
            direct_url=None,
            requires=distribution_requires,
        )

    # The source imports a module of ``top``, so the install must record
    # the module file for the import to be attributed to the distribution.
    module_directory = site_packages / chain.top_module
    module_directory.mkdir()
    (module_directory / "__init__.py").touch()
    record = site_packages / f"{chain.top_module}-1.0.dist-info" / "RECORD"
    with record.open("a", encoding="utf-8") as record_file:
        record_file.write(f"{chain.top_module}/__init__.py,,\n")

    # The parameter has no annotation until
    # https://github.com/pytest-dev/pytest/pull/14988 is released.
    monkeypatch.syspath_prepend(  # pyright: ignore[reportUnknownMemberType]
        str(site_packages),
    )
    common.get_packages_info.cache_clear()

    yield chain

    common.get_packages_info.cache_clear()
