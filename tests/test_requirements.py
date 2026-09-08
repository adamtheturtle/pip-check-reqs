"""Tests for `requirements.py`."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
from packaging.requirements import Requirement

from pip_check_reqs import common, requirements

from .conftest import write_dist_info

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .conftest import EditableInstall


def test_requirements_file_specs(tmp_path: Path) -> None:
    """Each line of a requirements file gives a record of the requirement."""
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        'foobar==1\nbarfoo==2; python_version < "2.0"\n',
    )

    specs = list(
        requirements.requirements_file_specs(path=fake_requirements_file),
    )

    assert [spec.name for spec in specs] == ["foobar", "barfoo"]
    assert [spec.text for spec in specs] == [
        "foobar==1",
        'barfoo==2; python_version < "2.0"',
    ]
    assert specs[0].marker is None
    assert specs[1].marker is not None
    assert not specs[1].marker.evaluate()


def _spec(text: str) -> requirements.RequirementSpec:
    """Return a requirement record for a requirement string."""
    requirement = Requirement(text)
    return requirements.RequirementSpec(
        name=requirement.name,
        marker=requirement.marker,
        text=text,
    )


def test_find_required_modules() -> None:
    reqs = requirements.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=["barfoo"]),
        skip_incompatible=False,
        specs=[_spec("foobar==1"), _spec("barfoo==2")],
    )
    assert reqs == {"foobar"}


def test_find_required_modules_normalizes_names() -> None:
    """A name is normalized so that it matches an installed distribution."""
    reqs = requirements.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=False,
        specs=[_spec("Foo_Bar==1")],
    )
    assert reqs == {"foo-bar"}


def test_find_required_modules_env_markers() -> None:
    reqs = requirements.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=True,
        specs=[
            _spec('spam==1; python_version<"2.0"'),
            _spec("ham==2"),
            _spec("eggs==3"),
        ],
    )
    assert reqs == {"ham", "eggs"}


def test_find_required_modules_keeps_incompatible() -> None:
    """An incompatible requirement is kept unless asked to skip it."""
    reqs = requirements.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=False,
        specs=[_spec('spam==1; python_version<"2.0"')],
    )
    assert reqs == {"spam"}


def test_requirements_file_specs_marker_with_quoted_semicolon(
    tmp_path: Path,
) -> None:
    """A ``;`` inside a quoted marker value does not end the marker."""
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        'spam==1; python_version < "2.0" or platform_release == "a;b"\n'
        'eggs==3; python_version > "2.0" or platform_release == "a;b"\n',
    )

    specs = list(
        requirements.requirements_file_specs(path=fake_requirements_file),
    )

    assert [spec.name for spec in specs] == ["spam", "eggs"]
    spam_marker, eggs_marker = (spec.marker for spec in specs)
    assert spam_marker is not None
    assert eggs_marker is not None
    assert not spam_marker.evaluate()
    assert eggs_marker.evaluate()


def test_requirements_file_specs_unnamed_requirement(tmp_path: Path) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    url = "git+ssh://git@example.com/org/repo.git"
    fake_requirements_file.write_text(f"foobar==1\n{url}\n")

    with pytest.raises(ValueError, match="requirement has no name") as excinfo:
        list(requirements.requirements_file_specs(path=fake_requirements_file))

    hint = (
        "Install it, or add an '#egg=<name>' fragment naming the distribution."
    )
    expected_message = f"requirement has no name: {url}. {hint}"
    assert str(excinfo.value) == expected_message


def test_requirements_file_specs_egg_fragment_names_requirement(
    tmp_path: Path,
) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    url = "git+ssh://git@example.com/org/repo.git#egg=repo"
    fake_requirements_file.write_text(f"foobar==1\n{url}\n")

    specs = requirements.requirements_file_specs(path=fake_requirements_file)

    assert [spec.name for spec in specs] == ["foobar", "repo"]


def test_pyproject_specs(tmp_path: Path) -> None:
    """Each ``[project]`` dependency gives a record of the requirement."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        data=textwrap.dedent(
            text="""\
            [project]
            name = "spam"
            dependencies = [
                "foobar==1",
                'barfoo==2; python_version < "2.0"',
            ]
            """,
        ),
    )

    specs = list(requirements.pyproject_specs(path=pyproject))

    assert [spec.name for spec in specs] == ["foobar", "barfoo"]
    assert [spec.text for spec in specs] == [
        "foobar==1",
        'barfoo==2; python_version < "2.0"',
    ]
    assert specs[0].marker is None
    assert specs[1].marker is not None
    assert not specs[1].marker.evaluate()


def test_pyproject_specs_no_project_table(tmp_path: Path) -> None:
    """A file with no ``[project]`` table declares no requirements."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(data='[build-system]\nrequires = ["setuptools"]\n')

    assert not list(requirements.pyproject_specs(path=pyproject))


def test_pyproject_specs_no_dependencies(tmp_path: Path) -> None:
    """A ``[project]`` table with no dependencies declares no requirements."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(data='[project]\nname = "spam"\n')

    assert not list(requirements.pyproject_specs(path=pyproject))


def test_pyproject_specs_invalid_requirement(tmp_path: Path) -> None:
    """A dependency which is not a requirement string gives an error."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        data='[project]\nname = "spam"\ndependencies = ["foo bar =="]\n',
    )

    with pytest.raises(expected_exception=ValueError, match="foo bar =="):
        list(requirements.pyproject_specs(path=pyproject))


def test_requirement_specs_pyproject(tmp_path: Path) -> None:
    """A file named ``pyproject.toml`` is read as a project file."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        data='[project]\nname = "spam"\ndependencies = ["foobar==1"]\n',
    )

    specs = list(requirements.requirement_specs(path=pyproject))

    assert [spec.name for spec in specs] == ["foobar"]


def test_requirement_specs_requirements_file(tmp_path: Path) -> None:
    """Any other file is read as a requirements file."""
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text(data="foobar==1\n")

    specs = list(requirements.requirement_specs(path=requirements_file))

    assert [spec.name for spec in specs] == ["foobar"]


def _editable_line(directory: Path) -> str:
    """Return an ``-e`` requirement line for a directory.

    pip splits an editable line as a shell does, so a backslash in a Windows
    path is lost. Windows accepts a forward slash instead.
    """
    return f"-e {directory.as_posix()}"


def _file_url_line(directory: Path) -> str:
    """Return a ``file`` URL requirement line for a directory."""
    return directory.as_uri()


@pytest.mark.parametrize(
    "line_for_directory",
    [
        pytest.param(_editable_line, id="editable"),
        pytest.param(str, id="not editable"),
        pytest.param(_file_url_line, id="file URL"),
    ],
)
def test_requirements_file_specs_installed_directory_requirement(
    *,
    editable_install: EditableInstall,
    tmp_path: Path,
    line_for_directory: Callable[[Path], str],
) -> None:
    """A local directory requirement is named by the install made from it.

    ``-e .`` is a common line in a requirements file, and it carries no
    distribution name. The install records the directory it was made from,
    so the name is taken from the install.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    line = line_for_directory(editable_install.source_directory)
    fake_requirements_file.write_text(f"foobar==1\n{line}\n")

    specs = requirements.requirements_file_specs(path=fake_requirements_file)

    assert [spec.name for spec in specs] == [
        "foobar",
        editable_install.distribution_name,
    ]


def test_requirements_file_specs_relative_directory_requirement(
    *,
    editable_install: EditableInstall,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A directory requirement is matched to an install by its resolved path.

    A requirements file usually names the project directory relative to the
    working directory, as ``-e .`` does, while the install records an
    absolute ``file`` URL.
    """
    monkeypatch.chdir(editable_install.source_directory)
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("-e .\n")

    specs = requirements.requirements_file_specs(path=fake_requirements_file)

    assert [spec.name for spec in specs] == [
        editable_install.distribution_name,
    ]


@pytest.mark.parametrize(
    ("line", "direct_url"),
    [
        pytest.param(
            "git+https://example.com/org/repo.git@v1.0#subdirectory=sub",
            {
                "url": "https://example.com/org/repo.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
                "subdirectory": "sub",
            },
            id="git with revision and subdirectory",
        ),
        pytest.param(
            "git+ssh://git@example.com/org/repo.git",
            {
                "url": "ssh://git@example.com/org/repo.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
            },
            id="git over ssh",
        ),
        pytest.param(
            "https://example.com/downloads/repo-1.0.tar.gz",
            {
                "url": "https://example.com/downloads/repo-1.0.tar.gz",
                "archive_info": {},
            },
            id="archive",
        ),
    ],
)
def test_requirements_file_specs_installed_url_requirement(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    line: str,
    direct_url: dict[str, object],
) -> None:
    """A URL requirement is named by the install made from that URL.

    A requirement may pin a revision, which the install does not record as
    part of the URL, so the revision is left out when matching. A repository
    may hold several projects, so the subdirectory is matched too.
    """
    distribution_name = "url-package-12345"
    site_packages = tmp_path / "site-packages"
    write_dist_info(
        site_packages=site_packages,
        distribution_name=distribution_name,
        direct_url=direct_url,
    )
    # The parameter has no annotation until
    # https://github.com/pytest-dev/pytest/pull/14988 is released.
    monkeypatch.syspath_prepend(  # pyright: ignore[reportUnknownMemberType]
        str(site_packages),
    )
    requirements.direct_url_distribution_names.cache_clear()

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(f"foobar==1\n{line}\n")

    try:
        specs = list(
            requirements.requirements_file_specs(path=fake_requirements_file),
        )
    finally:
        requirements.direct_url_distribution_names.cache_clear()

    assert [spec.name for spec in specs] == ["foobar", distribution_name]


def test_requirements_file_specs_unparseable_requirement(
    tmp_path: Path,
) -> None:
    """A requirement which pip cannot read is reported as an input error.

    A directory with no ``pyproject.toml`` or ``setup.py`` is not a project,
    so pip refuses it. That previously surfaced as a pip traceback.
    """
    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(f"{empty_directory}\n")

    with pytest.raises(ValueError, match="could not parse") as excinfo:
        list(requirements.requirements_file_specs(path=fake_requirements_file))

    # pip quotes the directory as Python does, so a backslash in a Windows
    # path is doubled.
    expected_message = (
        f"could not parse requirement: Directory {str(empty_directory)!r} is "
        "not installable. Neither 'setup.py' nor 'pyproject.toml' found."
    )
    assert str(excinfo.value) == expected_message
