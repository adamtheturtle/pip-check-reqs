from __future__ import absolute_import

import ast
import builtins
import logging
import optparse
import os.path
import textwrap
from copy import copy
from pathlib import Path
from typing import Any, List, Tuple

import pytest
from pytest import MonkeyPatch

from pip_check_reqs import __version__, common


@pytest.mark.parametrize(
    ["path", "result"],
    [
        ("/", ""),
        ("__init__.py", ""),  # a top-level file like this has no package name
        ("/__init__.py", ""),  # no package name
        ("spam/__init__.py", "spam"),
        ("spam/__init__.pyc", "spam"),
        ("spam/__init__.pyo", "spam"),
        ("ham/spam/__init__.py", "ham/spam"),
        ("/ham/spam/__init__.py", "/ham/spam"),
    ],
)
def test_is_package_file(path: str, result: str) -> None:
    assert common.is_package_file(path) == result


def test_FoundModule() -> None:
    fm = common.FoundModule("spam", "ham")
    assert fm.modname == "spam"
    assert fm.filename == os.path.realpath("ham")
    assert fm.locations == []


@pytest.mark.parametrize(
    ["stmt", "result"],
    [
        ("import ast", ["ast"]),
        ("import ast, pathlib", ["ast", "pathlib"]),
        ("from pathlib import Path", ["pathlib"]),
        ("from string import hexdigits", ["string"]),
        ("import distutils.command.check", ["distutils"]),
        ("import spam", []),  # don't break because bad programmer
    ],
)
def test_ImportVisitor(stmt: str, result: List[str]) -> None:
    def ignore_mods(modname: str) -> bool:
        return False

    options = optparse.Values()
    options.ignore_mods = ignore_mods

    vis = common.ImportVisitor(options)
    vis.set_location("spam.py")
    vis.visit(ast.parse(stmt))
    finalise_result = vis.finalise()
    assert set(finalise_result.keys()) == set(result)


def test_pyfiles_file(tmp_path: Path) -> None:
    python_file = tmp_path / "example.py"
    python_file.touch()
    assert list(common.pyfiles(root=str(python_file))) == [str(python_file)]


def test_pyfiles_file_no_dice(tmp_path: Path) -> None:
    not_python_file = tmp_path / "example"
    not_python_file.touch()

    with pytest.raises(ValueError):
        list(common.pyfiles(root=str(not_python_file)))


def test_pyfiles_package(tmp_path: Path) -> None:
    python_file = tmp_path / "example.py"
    nested_python_file = tmp_path / "subdir" / "example.py"
    not_python_file = tmp_path / "example"

    python_file.touch()
    nested_python_file.parent.mkdir()
    nested_python_file.touch()

    not_python_file.touch()

    assert list(common.pyfiles(root=str(tmp_path))) == [
        str(python_file),
        str(nested_python_file),
    ]


# Beware - using "sys" or "os" here can have weird results.
# See the comment in the implementation.
# We don't mind so much as we only really use this for third party packages.
@pytest.mark.parametrize(
    ["ignore_ham", "ignore_hashlib", "expect", "locs"],
    [
        (
            False,
            False,
            ["ast", "pathlib", "hashlib"],
            [
                ("spam.py", 2),
                ("ham.py", 2),
            ],
        ),
        (False, True, ["ast", "pathlib"], [("spam.py", 2), ("ham.py", 2)]),
        (True, False, ["ast"], [("spam.py", 2)]),
        (True, True, ["ast"], [("spam.py", 2)]),
    ],
)
def test_find_imported_modules(
    caplog: pytest.LogCaptureFixture,
    ignore_ham: bool,
    ignore_hashlib: bool,
    expect: List[str],
    locs: List[Tuple[str, int]],
    tmp_path: Path,
) -> None:
    root = tmp_path
    spam = root / "spam.py"
    ham = root / "ham.py"

    spam_file_contents = textwrap.dedent(
        """\
        from __future__ import braces
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
        if Path(path).name == "ham.py" and ignore_ham:
            return True
        return False

    def ignore_mods(module: str) -> bool:
        if module == "hashlib" and ignore_hashlib:
            return True
        return False

    options = optparse.Values()
    options.paths = [str(root)]
    options.verbose = True
    options.ignore_files = ignore_files
    options.ignore_mods = ignore_mods

    result = common.find_imported_modules(options)
    assert set(result) == set(expect)
    absolute_locations = result["ast"].locations
    relative_locations = [
        (str(Path(item[0]).relative_to(root)), item[1])
        for item in absolute_locations
    ]
    assert sorted(relative_locations) == sorted(locs)

    if ignore_ham:
        assert caplog.records[0].message == f"ignoring: {os.path.relpath(ham)}"


@pytest.mark.parametrize(
    ["ignore_cfg", "candidate", "result"],
    [
        ([], "spam", False),
        ([], "ham", False),
        (["spam"], "spam", True),
        (["spam"], "spam.ham", False),
        (["spam"], "eggs", False),
        (["spam*"], "spam", True),
        (["spam*"], "spam.ham", True),
        (["spam*"], "eggs", False),
        (["spam"], "/spam", True),
    ],
)
def test_ignorer(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    ignore_cfg: List[str],
    candidate: str,
    result: bool,
) -> None:
    monkeypatch.setattr(os.path, "relpath", lambda s: s.lstrip("/"))
    ignorer = common.ignorer(ignore_cfg)
    assert ignorer(candidate) == result


def test_find_required_modules(tmp_path: Path) -> None:
    options = optparse.Values()
    options.skip_incompatible = False
    options.ignore_reqs = common.ignorer(ignore_cfg=["barfoo"])

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("foobar==1\nbarfoo==2")

    reqs = common.find_required_modules(
        options=options,
        requirements_filename=str(fake_requirements_file),
    )
    assert reqs == set(["foobar"])


def test_find_required_modules_env_markers(tmp_path: Path) -> None:
    def ignore_reqs(modname: str) -> bool:
        return False

    options = optparse.Values()
    options.skip_incompatible = True
    options.ignore_reqs = ignore_reqs

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        'spam==1; python_version<"2.0"\n' "ham==2;\n" "eggs==3\n"
    )

    reqs = common.find_required_modules(
        options=options,
        requirements_filename=str(fake_requirements_file),
    )
    assert reqs == {"ham", "eggs"}


def test_find_imported_modules_sets_encoding_to_utf8_when_reading(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "module.py").touch()

    def ignore_files(filename: str) -> bool:
        return False

    options = optparse.Values()
    options.paths = [tmp_path]
    options.ignore_files = ignore_files

    expected_encoding = "utf-8"
    used_encoding = None

    original_open = copy(builtins.open)

    def mocked_open(*args: Any, **kwargs: Any) -> Any:
        # As of Python 3.9, the args to open() are as follows:
        # file, mode, buffering, encoding, erorrs, newline, closedf, opener
        nonlocal used_encoding
        if "encoding" in kwargs:
            used_encoding = kwargs["encoding"]
        return original_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", mocked_open)
    common.find_imported_modules(options)

    assert used_encoding == expected_encoding


def test_version_info_shows_version_number() -> None:
    assert __version__ in common.version_info()
