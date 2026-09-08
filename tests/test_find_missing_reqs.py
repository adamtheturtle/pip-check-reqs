"""Tests for `find_missing_reqs.py`."""

from __future__ import annotations

import logging
import re
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pip  # This happens to be installed in the test environment.
import pytest

from pip_check_reqs import common, find_missing_reqs

if TYPE_CHECKING:
    from .conftest import DependencyChain, EditableInstall, NestedInstall


def test_find_missing_reqs(tmp_path: Path) -> None:
    installed_imported_not_required_package = pytest
    installed_imported_required_package = pip

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        textwrap.dedent(
            f"""\
            not_installed_package_12345==1
            {installed_imported_required_package.__name__}
            """,
        ),
    )

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    source_file.write_text(
        textwrap.dedent(
            f"""\
            import pprint

            import {installed_imported_not_required_package.__name__}
            import {installed_imported_required_package.__name__}
            """,
        ),
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )
    expected_result = [
        (
            installed_imported_not_required_package.__name__,
            [
                common.FoundModule(
                    modname=installed_imported_not_required_package.__name__,
                    filename=Path(
                        installed_imported_not_required_package.__file__,
                    ).parent,
                    locations=[(str(source_file), 3)],
                ),
            ],
        ),
    ]
    assert result.used == expected_result


def test_uninstalled_import_is_reported(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """An import of a module which is not installed is reported.

    We know which requirement provides a module from the files of the
    installed distribution, so we cannot tell whether such an import is
    required, and we say so rather than passing it over.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("pytest\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    source_file.write_text("import not_installed_package_12345\n")

    caplog.set_level(logging.WARNING)

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )

    assert not result.used
    expected_message = (
        f"{source_file}:1 module=not_installed_package_12345 is not "
        "installed, so we cannot tell which requirement provides it"
    )
    assert [record.message for record in caplog.records] == [expected_message]


def test_uninstalled_import_of_requirement_is_not_reported(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """An import of a listed but uninstalled requirement is not reported.

    The requirement is in the requirements file, so nothing is missing.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("Not-Installed-Package-12345==1\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import not_installed_package_12345")

    caplog.set_level(logging.WARNING)

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )

    assert not result.used
    assert not caplog.records


def test_main_uninstalled_import_does_not_fail(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """An uninstalled import is a warning rather than a failure.

    An import which we cannot resolve is not always a mistake, as a module
    of the source may be given by a path we do not scan, so we do not fail
    the run for it.
    """
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "source.py"
    source_file.write_text("import not_installed_package_12345\n")

    caplog.set_level(logging.WARNING)

    find_missing_reqs.main(
        arguments=[
            "--requirements",
            str(requirements_file),
            str(source_dir),
        ],
    )

    expected_message = (
        f"{source_file}:1 module=not_installed_package_12345 is not "
        "installed, so we cannot tell which requirement provides it"
    )
    assert [record.message for record in caplog.records] == [expected_message]


def test_main_ignore_module_silences_uninstalled_import(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import not_installed_package_12345")

    caplog.set_level(logging.WARNING)

    find_missing_reqs.main(
        arguments=[
            "--requirements",
            str(requirements_file),
            "--ignore-module",
            "not_installed_package_12345",
            str(source_dir),
        ],
    )

    assert not caplog.records


def test_main_multiple_requirements_files(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    first_requirements_file = tmp_path / "requirements.txt"
    first_requirements_file.write_text("pip\n")
    second_requirements_file = tmp_path / "test-requirements.txt"
    second_requirements_file.write_text("pytest\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pip\nimport pytest\n")

    find_missing_reqs.main(
        arguments=[
            "--requirements-file",
            str(first_requirements_file),
            "--requirements-file",
            str(second_requirements_file),
            str(source_dir),
        ],
    )

    assert not caplog.records


def test_main_pyproject_requirements_file(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """A ``pyproject.toml`` file given as the requirements file is read."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        data='[project]\nname = "spam"\ndependencies = ["pip"]\n',
    )

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pip\nimport pytest\n")

    caplog.set_level(logging.WARNING)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements-file",
                str(pyproject),
                str(source_dir),
            ],
        )

    assert excinfo.value.code == 1
    assert [record.message for record in caplog.records] == [
        "Missing requirements:",
        f"{source_dir / 'source.py'}:2 dist=pytest module=pytest",
    ]


def test_main_failure(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    # We need to import something which is installed.
    # We choose `pytest` because we know it is installed.
    source_file.write_text("import pytest")

    caplog.set_level(logging.WARNING)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    assert excinfo.value.code == 1

    assert caplog.records[0].message == "Missing requirements:"
    assert (
        caplog.records[1].message
        == f"{source_file}:1 dist=pytest module=pytest"
    )


def test_main_use_gitignore(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """With ``--use-gitignore``, a file a ``.gitignore`` ignores is skipped.

    A module which only an ignored file provides is then not known to be
    provided by the source, so an import of it is reported as uninstalled.
    """
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    # We need to import something which is installed.
    # We choose `pytest` because we know it is installed.
    ignored_file = source_dir / "ignored.py"
    ignored_file.write_text("import pytest")
    source_file = source_dir / "source.py"
    source_file.write_text("import ignored")

    caplog.set_level(logging.WARNING)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    assert excinfo.value.code == 1
    assert [record.message for record in caplog.records] == [
        "Missing requirements:",
        f"{ignored_file}:1 dist=pytest module=pytest",
    ]

    caplog.clear()
    find_missing_reqs.main(
        arguments=[
            "--requirements",
            str(requirements_file),
            "--use-gitignore",
            str(source_dir),
        ],
    )

    assert [record.message for record in caplog.records] == [
        (
            f"{source_file}:1 module=ignored is not installed, so we cannot "
            "tell which requirement provides it"
        ),
    ]


def test_main_no_spec(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(arguments=[])

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith("error: no source files or directories specified\n")


def test_main_missing_requirements_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    requirements_file = tmp_path / "missing-requirements.txt"

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith(
        f"error: requirements file not found: {requirements_file}\n",
    )


def test_main_missing_source_path(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()
    source_dir = tmp_path / "missing-source"

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith(f"error: source path not found: {source_dir}\n")


def test_main_source_file_parse_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "spam.py"
    source_file.write_text(data="def (\n")

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith(
        f"error: could not parse {source_file}:1: invalid syntax\n",
    )


def test_main_unnamed_requirement(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    url = "git+ssh://git@example.com/org/repo.git"
    requirements_file.write_text(f"{url}\n")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pytest\n")

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    hint = (
        "Install it, or add an '#egg=<name>' fragment naming the distribution."
    )
    assert err.endswith(f"error: requirement has no name: {url}. {hint}\n")


def test_main_editable_directory_requirement(
    *,
    caplog: pytest.LogCaptureFixture,
    editable_install: EditableInstall,
    tmp_path: Path,
) -> None:
    """An ``-e <directory>`` line satisfies the imports of the install.

    Such a line carries no distribution name, so it previously stopped the
    check with an error asking for one.
    """
    requirements_file = tmp_path / "requirements.txt"
    # pip splits an editable line as a shell does, so a backslash in a
    # Windows path is lost. Windows accepts a forward slash instead.
    directory = editable_install.source_directory.as_posix()
    requirements_file.write_text(f"-e {directory}\n")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text(
        f"import {editable_install.module_name}\n",
    )

    find_missing_reqs.main(
        arguments=[
            "--requirements",
            str(requirements_file),
            str(source_dir),
        ],
    )

    assert not caplog.records


def test_main_egg_fragment_names_requirement(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    url = "git+ssh://git@example.com/org/repo.git#egg=pytest"
    requirements_file.write_text(f"{url}\n")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pytest\n")

    find_missing_reqs.main(
        arguments=[
            "--requirements",
            str(requirements_file),
            str(source_dir),
        ],
    )

    assert not caplog.records


def test_main_debug_reraises_input_error(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    requirements_file = tmp_path / "missing-requirements.txt"

    with pytest.raises(
        FileNotFoundError,
        match=re.escape(f"requirements file not found: {requirements_file}"),
    ):
        find_missing_reqs.main(
            arguments=[
                "--debug",
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )


@pytest.mark.parametrize(
    ("verbose_cfg", "debug_cfg", "expected_log_levels"),
    [
        (False, False, {logging.WARNING}),
        (True, False, {logging.INFO, logging.WARNING}),
        (False, True, {logging.DEBUG, logging.INFO, logging.WARNING}),
        (True, True, {logging.DEBUG, logging.INFO, logging.WARNING}),
    ],
)
def test_logging_config(
    *,
    caplog: pytest.LogCaptureFixture,
    verbose_cfg: bool,
    debug_cfg: bool,
    expected_log_levels: set[int],
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    arguments = [str(source_dir)]
    if verbose_cfg:
        arguments.append("--verbose")
    if debug_cfg:
        arguments.append("--debug")

    find_missing_reqs.main(arguments=arguments)

    for event in [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
    ]:
        find_missing_reqs.log.log(*event)

    log_levels = {r.levelno for r in caplog.records}
    assert log_levels == expected_log_levels


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        find_missing_reqs.main(arguments=["--version"])

    assert capsys.readouterr().out == common.version_info() + "\n"


def test_main_warns_when_run_from_another_environment(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pprint")

    # We resolve the path as the warning shows resolved paths, and a
    # temporary directory is reached through a symbolic link on some hosts.
    active_prefix = (tmp_path / "active").resolve()
    monkeypatch.setenv("VIRTUAL_ENV", str(active_prefix))

    find_missing_reqs.main(
        arguments=[
            "--requirements-file",
            str(requirements_file),
            str(source_dir),
        ],
    )

    running_prefix = Path(sys.prefix).resolve()
    expected_stderr = (
        f"WARNING: Running from {running_prefix}, but the active "
        f"virtual environment is {active_prefix}. "
        "Results describe the environment pip-check-reqs is installed in. "
        "Install pip-check-reqs in the active virtual environment, and "
        'run "hash -r" ("rehash" in zsh), to check that environment.\n'
    )
    assert capsys.readouterr().err == expected_stderr


def test_main_does_not_warn_when_run_from_the_active_environment(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pprint")

    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)

    find_missing_reqs.main(
        arguments=[
            "--requirements-file",
            str(requirements_file),
            str(source_dir),
        ],
    )

    assert capsys.readouterr().err == ""


def test_editable_requirement_is_missing(
    *,
    editable_install: EditableInstall,
    tmp_path: Path,
) -> None:
    """An import of an editable install which is not required is reported.

    The files of an editable install are an import hook rather than the
    modules of the distribution, so the modules it provides are only found by
    looking at the project directory which it is installed from.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "source.py"
    source_file.write_text(f"import {editable_install.module_name}\n")

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )

    (name, uses) = next(iter(result.used))
    assert name == editable_install.distribution_name
    assert [use.modname for use in uses] == [editable_install.module_name]


def test_own_source_installed_as_editable_is_not_missing(
    *,
    editable_install: EditableInstall,
    tmp_path: Path,
) -> None:
    """The source we scan is not a requirement of itself.

    A project is commonly installed in editable mode while it is worked on,
    and its own modules are then provided by an editable install. They are
    the source we check rather than a distribution it requires, so they are
    not reported.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("")

    source_file = (
        editable_install.source_directory
        / editable_install.module_name
        / "uses_own_package.py"
    )
    source_file.write_text(f"import {editable_install.module_name}\n")

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[editable_install.source_directory],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )

    assert not result.used


def test_transitive_dependencies_are_reported(
    *,
    dependency_chain: DependencyChain,
    tmp_path: Path,
) -> None:
    """Unlisted dependencies of a used distribution are reported.

    They are followed recursively and each is reported with the
    distributions which require it. A dependency which is not installed is
    reported but cannot be followed further. A dependency of an extra is
    only followed when the extra is asked for, and a dependency with an
    environment marker is only followed when the marker holds.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(f"{dependency_chain.top}\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text(
        f"import {dependency_chain.top_module}\n",
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        transitive=True,
        use_gitignore=False,
    )

    assert not result.used
    assert result.transitive == {
        dependency_chain.middle: {dependency_chain.top},
        dependency_chain.bottom: {dependency_chain.middle},
        dependency_chain.uninstalled: {dependency_chain.middle},
        dependency_chain.fast: {dependency_chain.bottom},
    }


def test_transitive_dependencies_are_not_checked_by_default(
    *,
    dependency_chain: DependencyChain,
    tmp_path: Path,
) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(f"{dependency_chain.top}\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text(
        f"import {dependency_chain.top_module}\n",
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )

    assert not result.used
    assert not result.transitive


def test_listed_transitive_dependencies_are_not_reported(
    *,
    dependency_chain: DependencyChain,
    tmp_path: Path,
) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        textwrap.dedent(
            f"""\
            {dependency_chain.top}
            {dependency_chain.middle}
            {dependency_chain.bottom}
            {dependency_chain.fast}
            {dependency_chain.uninstalled}
            """,
        ),
    )

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text(
        f"import {dependency_chain.top_module}\n",
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        transitive=True,
        use_gitignore=False,
    )

    assert not result.used
    assert not result.transitive


def test_used_distribution_is_not_reported_as_transitive(
    *,
    dependency_chain: DependencyChain,
    tmp_path: Path,
) -> None:
    """A used distribution is reported once, with the imports which use it.

    ``bottom`` requires ``top``, which the source imports, so ``top`` is also
    a transitive dependency. It is reported as a missing requirement of the
    source and not a second time as a dependency.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text(
        f"import {dependency_chain.top_module}\n",
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        transitive=True,
        use_gitignore=False,
    )

    assert [name for name, _ in result.used] == [dependency_chain.top]
    assert dependency_chain.top not in result.transitive
    assert dependency_chain.middle in result.transitive


def test_main_transitive(
    *,
    dependency_chain: DependencyChain,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """Each unlisted dependency is reported with what requires it."""
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text(f"{dependency_chain.top}\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text(
        f"import {dependency_chain.top_module}\n",
    )

    caplog.set_level(logging.WARNING)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements-file",
                str(requirements_file),
                "--transitive",
                str(source_dir),
            ],
        )

    assert excinfo.value.code == 1
    assert [record.message for record in caplog.records] == [
        "Missing requirements:",
        (
            f"dist={dependency_chain.bottom} required by "
            f"{dependency_chain.middle}"
        ),
        f"dist={dependency_chain.fast} required by {dependency_chain.bottom}",
        f"dist={dependency_chain.middle} required by {dependency_chain.top}",
        (
            f"dist={dependency_chain.uninstalled} required by "
            f"{dependency_chain.middle}"
        ),
    ]


def test_import_installed_within_working_directory_is_missing(
    *,
    nested_install: NestedInstall,
    tmp_path: Path,
) -> None:
    """An unlisted import from a nested environment is reported.

    The environment is inside the working directory, as when it is created
    with ``python -m venv env`` in the project directory.

    See https://github.com/adamtheturtle/pip-check-reqs/issues/75.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "source.py"
    source_file.write_text(f"import {nested_install.module_name}\n")

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.file_ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        use_gitignore=False,
    )

    (name, uses) = next(iter(result.used))
    assert name == nested_install.distribution_name
    assert [use.modname for use in uses] == [nested_install.module_name]
