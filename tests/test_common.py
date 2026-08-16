"""Tests for `common.py`."""

from __future__ import annotations

import logging
import platform
import re
import sys
import textwrap
import types
import uuid
from pathlib import Path

import pytest

import __main__
from pip_check_reqs import __version__, common


@pytest.mark.parametrize(
    ("path", "result"),
    [
        (Path("/"), None),
        (Path("/ham/spam/other.py"), None),
        (Path("/ham/spam"), None),
        # a top-level file like this has no package path
        (Path("__init__.py"), None),
        (Path("/__init__.py"), None),  # no package name
        (Path("spam/__init__.py"), Path("spam")),
        (Path("spam/__init__.pyc"), Path("spam")),
        (Path("spam/__init__.pyo"), Path("spam")),
        (Path("ham/spam/__init__.py"), Path("ham/spam")),
        (Path("/ham/spam/__init__.py"), Path("/ham/spam")),
    ],
)
def test_package_path(*, path: Path, result: Path) -> None:
    assert common.package_path(path=path) == result, path


def test_found_module() -> None:
    found_module = common.FoundModule(modname="spam", filename=Path("ham"))
    assert found_module.modname == "spam"
    assert found_module.filename == Path("ham").resolve()
    assert not found_module.locations


def test_pyfiles_file(tmp_path: Path) -> None:
    python_file = tmp_path / "example.py"
    python_file.touch()
    assert list(common.pyfiles(root=python_file)) == [python_file]


def test_pyfiles_file_no_dice(tmp_path: Path) -> None:
    not_python_file = tmp_path / "example"
    not_python_file.touch()

    with pytest.raises(
        expected_exception=ValueError,
        match=re.escape(
            f"{not_python_file} is not a python file or directory",
        ),
    ):
        list(common.pyfiles(root=not_python_file))


def test_pyfiles_package(tmp_path: Path) -> None:
    python_file = tmp_path / "example.py"
    nested_python_file = tmp_path / "subdir" / "example.py"
    not_python_file = tmp_path / "example"

    python_file.touch()
    nested_python_file.parent.mkdir()
    nested_python_file.touch()

    not_python_file.touch()

    assert list(common.pyfiles(root=tmp_path)) == [
        python_file,
        nested_python_file,
    ]


@pytest.mark.parametrize(
    argnames=("statement", "expected_module_names"),
    argvalues=[
        pytest.param("import ast", {"ast"}),
        pytest.param("import ast, pathlib", {"ast", "pathlib"}),
        pytest.param("from pathlib import Path", {"pathlib"}),
        pytest.param("from string import hexdigits", {"string"}),
        pytest.param("import urllib.request", {"urllib"}),
        pytest.param("import spam", set[str](), id="The file we are in"),
        pytest.param("from .foo import bar", set[str](), id="Relative import"),
        pytest.param("from . import baz", set[str]()),
        pytest.param(
            "import re",
            {"re"},
            id="Useful to confirm that the next test is valid",
        ),
        pytest.param(
            "import typing.re",
            {"typing"},
            id="Submodule has same name as a top-level module",
        ),
    ],
)
def test_find_imported_modules_simple(
    *,
    statement: str,
    expected_module_names: set[str],
    tmp_path: Path,
) -> None:
    """Test for the basic ability to find imported modules."""
    spam = tmp_path / "spam.py"
    spam.write_text(data=statement)

    result = common.find_imported_modules(
        paths=[tmp_path],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    ).found

    assert set(result.keys()) == expected_module_names
    for value in result.values():
        assert str(value.filename) not in sys.path
        assert value.filename.name != "__init__.py"
        assert value.filename.is_absolute()
        assert value.filename.exists()


def test_find_imported_modules_frozen(
    tmp_path: Path,
) -> None:
    """Frozen modules are not included in the result."""
    frozen_item_names: list[str] = []
    sys_module_items = list(sys.modules.items())
    for name, value in sys_module_items:
        try:
            spec = value.__spec__
        # No coverage as this does not occur on Python 3.13
        # with our current requirements.
        except AttributeError:  # pragma: no cover
            continue

        if spec is not None and spec.origin == "frozen":
            frozen_item_names.append(name)

    assert frozen_item_names, (
        "This test is only valid if there are frozen modules in sys.modules"
    )

    spam = tmp_path / "spam.py"
    statement = f"import {frozen_item_names[0]}"
    spam.write_text(data=statement)

    result = common.find_imported_modules(
        paths=[tmp_path],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    ).found

    assert set(result.keys()) == set()


@pytest.mark.skipif(
    condition=platform.system() == "Windows",
    reason=(
        "Test not supported on Windows, where __main__.__spec__ is not None"
    ),
)
def test_find_imported_modules_main(
    tmp_path: Path,
) -> None:  # pragma: no cover
    spam = tmp_path / "spam.py"
    statement = "import __main__"
    spam.write_text(data=statement)

    message = (
        "This test is only valid if __main__.__spec__ is None. "
        "That is not the case when running pytest as 'python -m pytest' "
        "which modifies sys.modules. "
        "See https://docs.pytest.org/en/7.1.x/how-to/usage.html#calling-pytest-from-python-code"
    )
    assert __main__.__spec__ is None, message

    result = common.find_imported_modules(
        paths=[tmp_path],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    ).found

    assert set(result.keys()) == set()


def test_find_imported_modules_no_spec(tmp_path: Path) -> None:
    """Modules without a __spec__ are not included in the result.

    This is often __main__.
    However, it is also possible to create a module without a __spec__.
    We prefer to test with a realistic case, but on Windows under `pytest`,
    `__main__.__spec__` is not None as `__main__` is replaced by pytest.

    Therefore we need this test to create a module without a __spec__.
    """
    spam = tmp_path / "spam.py"
    name = "a" + uuid.uuid4().hex
    statement = f"import {name}"
    spam.write_text(data=statement)
    module = types.ModuleType(name=name)
    module.__spec__ = None
    sys.modules[name] = module

    try:
        result = common.find_imported_modules(
            paths=[tmp_path],
            ignore_files_function=common.ignorer(ignore_cfg=[]),
            ignore_modules_function=common.ignorer(ignore_cfg=[]),
        ).found
    finally:
        del sys.modules[name]
    assert set(result.keys()) == set()


def test_find_imported_modules_syntax_error(tmp_path: Path) -> None:
    """A file which cannot be parsed gives an error naming file and line."""
    spam = tmp_path / "spam.py"
    spam.write_text(
        data=textwrap.dedent(
            text="""\
            import os

            def (
            """,
        ),
    )

    expected_message = f"could not parse {spam}:3: invalid syntax"
    with pytest.raises(
        expected_exception=ValueError,
        match=f"^{re.escape(expected_message)}$",
    ):
        common.find_imported_modules(
            paths=[tmp_path],
            ignore_files_function=common.ignorer(ignore_cfg=[]),
            ignore_modules_function=common.ignorer(ignore_cfg=[]),
        )


def test_find_imported_modules_period(tmp_path: Path) -> None:
    """Imported modules are found if the package name contains a period.

    An example of this is the module name `"ruamel.yaml"`.
    https://pypi.org/project/ruamel.yaml/

    In particular, `ruamel.yaml` is in `sys.modules` with a period in the name.
    """
    spam = tmp_path / "spam.py"
    statement = "import ruamel.yaml"
    spam.write_text(data=statement)

    result = common.find_imported_modules(
        paths=[tmp_path],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    ).found

    assert set(result.keys()) == {"ruamel.yaml"}


@pytest.mark.parametrize(
    "parent_name",
    [
        "pytest",
        "pprint",
    ],
)
def test_find_imported_modules_missing_from_submodule(
    parent_name: str,
    tmp_path: Path,
) -> None:
    """A missing sub-module is not attributed to its installed parent."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "example.py").write_text(
        f"from {parent_name}.missing import attribute",
    )

    result = common.find_imported_modules(
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    ).found

    assert not result


@pytest.mark.parametrize(
    ("ignore_ham", "ignore_hashlib", "expect", "locs"),
    [
        (
            False,
            False,
            ["ast", "pathlib", "hashlib", "sys"],
            [
                ("spam.py", 2),
                ("ham.py", 2),
            ],
        ),
        (
            False,
            True,
            ["ast", "pathlib", "sys"],
            [("spam.py", 2), ("ham.py", 2)],
        ),
        (True, False, ["ast", "sys"], [("spam.py", 2)]),
        (True, True, ["ast", "sys"], [("spam.py", 2)]),
    ],
)
def test_find_imported_modules_advanced(
    *,
    caplog: pytest.LogCaptureFixture,
    ignore_ham: bool,
    ignore_hashlib: bool,
    expect: list[str],
    locs: list[tuple[str, int]],
    tmp_path: Path,
) -> None:
    root = tmp_path
    spam = root / "spam.py"
    ham = root / "ham.py"

    spam_file_contents = textwrap.dedent(
        """\
        from __future__ import annotations
        import ast, sys
        from . import friend
        """,
    )
    ham_file_contents = textwrap.dedent(
        """\
        from pathlib import Path
        import ast, hashlib
        """,
    )

    spam.write_text(data=spam_file_contents)
    ham.write_text(data=ham_file_contents)

    caplog.set_level(logging.INFO)

    def ignore_files(path: str) -> bool:
        return bool(Path(path).name == "ham.py" and ignore_ham)

    def ignore_mods(module: str) -> bool:
        return bool(module == "hashlib" and ignore_hashlib)

    result = common.find_imported_modules(
        paths=[root],
        ignore_files_function=ignore_files,
        ignore_modules_function=ignore_mods,
    ).found
    assert set(result) == set(expect)
    absolute_locations = result["ast"].locations
    relative_locations = [
        (str(Path(item[0]).relative_to(root)), item[1])
        for item in absolute_locations
    ]
    assert sorted(relative_locations) == sorted(locs)

    if ignore_ham:
        assert caplog.records[0].message == f"ignoring: {ham}"


def test_find_imported_modules_uninstalled(tmp_path: Path) -> None:
    """An import of a module which is not installed is reported."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "spam.py"
    name = "a" + uuid.uuid4().hex
    source_file.write_text(
        data=textwrap.dedent(
            text=f"""\
            import re
            import {name}
            from {name}.ham import eggs
            """,
        ),
    )

    result = common.find_imported_modules(
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    )

    assert set(result.found) == {"re"}
    assert result.uninstalled == {
        name: [(str(source_file), 2), (str(source_file), 3)],
    }


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("import {name}.ham\n", id="Import"),
        pytest.param("from {name}.ham import eggs\n", id="ImportFrom"),
    ],
)
@pytest.mark.parametrize(
    "ignore_glob",
    [
        pytest.param("{name}", id="Top-level module name"),
        pytest.param("{name}*", id="Glob"),
        pytest.param("{name}.ham", id="Dotted import path"),
    ],
)
def test_find_imported_modules_uninstalled_ignored(
    *,
    ignore_glob: str,
    statement: str,
    tmp_path: Path,
) -> None:
    """An ignored module which is not installed is not reported."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    name = "a" + uuid.uuid4().hex
    (source_dir / "spam.py").write_text(data=statement.format(name=name))

    result = common.find_imported_modules(
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(
            ignore_cfg=[ignore_glob.format(name=name)],
        ),
    )

    assert not result.uninstalled


def test_find_imported_modules_uninstalled_no_spec(tmp_path: Path) -> None:
    """A module without a ``__spec__`` is available, so is not reported.

    See ``test_find_imported_modules_no_spec`` for how such a module comes
    about.
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    name = "a" + uuid.uuid4().hex
    (source_dir / "spam.py").write_text(data=f"from {name}.ham import eggs\n")
    module = types.ModuleType(name=name)
    module.__spec__ = None
    sys.modules[name] = module

    try:
        result = common.find_imported_modules(
            paths=[source_dir],
            ignore_files_function=common.ignorer(ignore_cfg=[]),
            ignore_modules_function=common.ignorer(ignore_cfg=[]),
        )
    finally:
        del sys.modules[name]

    assert not result.uninstalled


def test_find_imported_modules_uninstalled_submodule(tmp_path: Path) -> None:
    """A missing sub-module of an installed package is not reported.

    The distribution which would provide the sub-module is installed, so
    there is no requirement which we cannot check.
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "spam.py").write_text(
        data=textwrap.dedent(
            text="""\
            import pytest.missing
            from pytest.missing import attribute
            """,
        ),
    )

    result = common.find_imported_modules(
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    )

    assert not result.uninstalled


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("import spam", id="Module in the source"),
        pytest.param("import ham", id="Package in the source"),
        pytest.param("from ham.eggs import scrambled", id="Source submodule"),
        pytest.param("import source", id="Directory we scan"),
        pytest.param("import ignored", id="Ignored file in the source"),
    ],
)
def test_find_imported_modules_source_module(
    *,
    statement: str,
    tmp_path: Path,
) -> None:
    """A module which the scanned source provides is not reported.

    Such a module is not expected to be installed, so reporting it would be
    a false positive.
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "spam.py").write_text(data=statement)
    (source_dir / "ignored.py").touch()
    package_dir = source_dir / "ham"
    package_dir.mkdir()
    (package_dir / "__init__.py").touch()
    (package_dir / "eggs.py").touch()

    result = common.find_imported_modules(
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=["*ignored.py"]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    )

    assert not result.uninstalled


def test_source_module_names_file(tmp_path: Path) -> None:
    """A single source file gives its own module name."""
    source_file = tmp_path / "spam.py"
    source_file.touch()

    result = common.source_module_names(paths=[source_file])

    assert result == {"spam"}


@pytest.mark.parametrize(
    ("ignore_cfg", "candidate", "result"),
    [
        ([], "spam", False),
        ([], "ham", False),
        (["spam"], "spam", True),
        (["spam"], "spam.ham", False),
        (["spam"], "eggs", False),
        (["spam*"], "spam", True),
        (["spam*"], "spam.ham", True),
        (["spam*"], "eggs", False),
        (["spam"], str(Path.cwd() / "spam"), True),
        (["eggs"], str(Path.cwd() / "spam"), False),
        (["spam"], str(Path.cwd() / "eggs" / ".." / "spam"), True),
        (["spam"], str(Path("eggs") / ".." / "spam"), True),
        (["spam"], str(Path.cwd().parent / "spam"), False),
    ],
)
def test_ignorer(
    *,
    ignore_cfg: list[str],
    candidate: str,
    result: bool,
) -> None:
    ignorer = common.ignorer(ignore_cfg=ignore_cfg)
    assert ignorer(candidate) == result


@pytest.mark.skipif(
    condition=platform.system() != "Windows",
    reason="Only Windows has drives, which is what this test is about",
)
def test_ignorer_other_drive() -> None:  # pragma: no cover
    """A candidate on another drive than the working directory is handled.

    Making such a path relative to the working directory is impossible, and
    that used to raise an error.
    """
    working_directory_drive = Path.cwd().drive
    other_drive = "Y:" if working_directory_drive.upper() == "Z:" else "Z:"
    ignorer = common.ignorer(ignore_cfg=["eggs"])

    assert not ignorer(rf"{other_drive}\eggs\spam.py")


def test_find_required_modules(tmp_path: Path) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("foobar==1\nbarfoo==2")

    reqs = common.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=["barfoo"]),
        skip_incompatible=False,
        requirements_filename=fake_requirements_file,
    )
    assert reqs == {"foobar"}


def test_find_required_modules_env_markers(tmp_path: Path) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        'spam==1; python_version<"2.0"\nham==2;\neggs==3\n',
    )

    reqs = common.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=True,
        requirements_filename=fake_requirements_file,
    )
    assert reqs == {"ham", "eggs"}


def test_find_required_modules_unnamed_requirement(tmp_path: Path) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    url = "git+ssh://git@example.com/org/repo.git"
    fake_requirements_file.write_text(f"foobar==1\n{url}\n")

    with pytest.raises(ValueError, match="requirement has no name") as excinfo:
        common.find_required_modules(
            ignore_requirements_function=common.ignorer(ignore_cfg=[]),
            skip_incompatible=False,
            requirements_filename=fake_requirements_file,
        )

    hint = "Add an '#egg=<name>' fragment naming the distribution."
    expected_message = f"requirement has no name: {url}. {hint}"
    assert str(excinfo.value) == expected_message


def test_find_required_modules_egg_fragment_names_requirement(
    tmp_path: Path,
) -> None:
    fake_requirements_file = tmp_path / "requirements.txt"
    url = "git+ssh://git@example.com/org/repo.git#egg=repo"
    fake_requirements_file.write_text(f"foobar==1\n{url}\n")

    reqs = common.find_required_modules(
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=False,
        requirements_filename=fake_requirements_file,
    )
    assert reqs == {"foobar", "repo"}


def test_version_info_shows_version_number() -> None:
    major, minor, patch = sys.version_info[:3]
    python_version = f"{major}.{minor}.{patch}"
    parent_directory = Path(common.__file__).parent.resolve()
    expected_version_info = (
        f"pip-check-reqs {__version__} "
        f"from {parent_directory} "
        f"(python {python_version})"
    )
    assert common.version_info() == expected_version_info


def test_no_wrong_environment_warning_without_active_virtualenv(
    tmp_path: Path,
) -> None:
    warning = common.wrong_environment_warning(
        running_prefix=tmp_path,
        active_virtualenv=None,
        color=False,
    )
    assert warning is None


def test_no_wrong_environment_warning_from_active_virtualenv(
    tmp_path: Path,
) -> None:
    warning = common.wrong_environment_warning(
        running_prefix=tmp_path,
        active_virtualenv=str(tmp_path),
        color=False,
    )
    assert warning is None


def test_wrong_environment_warning(tmp_path: Path) -> None:
    # We resolve the paths as the warning shows resolved paths, and a
    # temporary directory is reached through a symbolic link on some hosts.
    active_prefix = (tmp_path / "active").resolve()
    running_prefix = (tmp_path / "running").resolve()

    warning = common.wrong_environment_warning(
        running_prefix=running_prefix,
        active_virtualenv=str(active_prefix),
        color=False,
    )

    expected_warning = (
        f"WARNING: Running from {running_prefix}, but the active "
        f"virtual environment is {active_prefix}. "
        "Results describe the environment pip-check-reqs is installed in. "
        "Install pip-check-reqs in the active virtual environment, and "
        'run "hash -r" ("rehash" in zsh), to check that environment.'
    )
    assert warning == expected_warning


def test_wrong_environment_warning_in_color(tmp_path: Path) -> None:
    active_prefix = (tmp_path / "active").resolve()
    running_prefix = (tmp_path / "running").resolve()

    warning = common.wrong_environment_warning(
        running_prefix=running_prefix,
        active_virtualenv=str(active_prefix),
        color=True,
    )

    plain_warning = common.wrong_environment_warning(
        running_prefix=running_prefix,
        active_virtualenv=str(active_prefix),
        color=False,
    )
    yellow = "\033[33m"
    reset = "\033[0m"
    assert warning == f"{yellow}{plain_warning}{reset}"
