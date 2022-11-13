from __future__ import absolute_import

import ast
import logging
import os.path
import textwrap
from pathlib import Path

import pytest
import pretend

from pip_check_reqs import common, __version__


@pytest.mark.parametrize(
    ["path", "result"],
    [
        ('/', ''),
        ('__init__.py', ''),  # a top-level file like this has no package name
        ('/__init__.py', ''),  # no package name
        ('spam/__init__.py', 'spam'),
        ('spam/__init__.pyc', 'spam'),
        ('spam/__init__.pyo', 'spam'),
        ('ham/spam/__init__.py', 'ham/spam'),
        ('/ham/spam/__init__.py', '/ham/spam'),
    ])
def test_is_package_file(path, result) -> None:
    assert common.is_package_file(path) == result


def test_FoundModule() -> None:
    fm = common.FoundModule('spam', 'ham')
    assert fm.modname == 'spam'
    assert fm.filename == os.path.realpath('ham')
    assert fm.locations == []


@pytest.mark.parametrize(
    ["stmt", "result"],
    [
        ('import ast', ['ast']),
        ('import ast, sys', ['ast', 'sys']),
        ('from sys import version', ['sys']),
        ('from os import path', ['os']),
        ('import distutils.command.check', ['distutils']),
        ('import spam', []),  # don't break because bad programmer
    ])
def test_ImportVisitor(stmt, result) -> None:
    class options:
        def ignore_mods(self, modname) -> bool:
            return False

    vis = common.ImportVisitor(options())
    vis.set_location('spam.py')
    vis.visit(ast.parse(stmt))
    result = vis.finalise()
    assert set(result.keys()) == set(result)


def test_pyfiles_file(monkeypatch) -> None:
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam/ham.py'))

    assert list(common.pyfiles('spam')) == ['/spam/ham.py']


def test_pyfiles_file_no_dice(monkeypatch) -> None:
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam/ham'))

    with pytest.raises(ValueError):
        list(common.pyfiles('spam'))


def test_pyfiles_package(monkeypatch) -> None:
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam'))
    monkeypatch.setattr(os.path, 'isdir',
                        pretend.call_recorder(lambda x: True))
    walk_results = [
        ('spam', [], ['__init__.py', 'spam', 'ham.py']),
        ('spam/dub', [], ['bass.py', 'dropped']),
    ]
    monkeypatch.setattr(os, 'walk',
                        pretend.call_recorder(lambda x: walk_results))

    assert list(common.pyfiles('spam')) == \
        ['spam/__init__.py', 'spam/ham.py', 'spam/dub/bass.py']


# Beware - using "sys" or "os" here can have weird results.
# See the comment in the implementation.
# We don't mind so much as we only really use this for third party packages.
@pytest.mark.parametrize(["ignore_ham", "ignore_hashlib", "expect", "locs"], [
    (
        False,
        False,
        ['ast', 'pathlib', 'hashlib'],
        [
            ('spam.py', 2),
            ('ham.py', 2),
        ],
    ),
    (False, True, ['ast', 'pathlib'], [('spam.py', 2), ('ham.py', 2)]),
    (True, False, ['ast'], [('spam.py', 2)]),
    (True, True, ['ast'], [('spam.py', 2)]),
])
def test_find_imported_modules(caplog, ignore_ham, ignore_hashlib,
                               expect, locs, tmp_path) -> None:
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

    class options:
        paths = [str(root)]
        verbose = True

        @staticmethod
        def ignore_files(path) -> bool:
            if Path(path).name == 'ham.py' and ignore_ham:
                return True
            return False

        @staticmethod
        def ignore_mods(module) -> bool:
            if module == 'hashlib' and ignore_hashlib:
                return True
            return False

    result = common.find_imported_modules(options)
    assert set(result) == set(expect)
    absolute_locations = result['ast'].locations
    relative_locations = [
        (str(Path(item[0]).relative_to(root)), item[1])
        for item in absolute_locations
    ]
    assert sorted(relative_locations) == sorted(locs)

    if ignore_ham:
        assert caplog.records[0].message == f'ignoring: {os.path.relpath(ham)}'


@pytest.mark.parametrize(["ignore_cfg", "candidate", "result"], [
    ([], 'spam', False),
    ([], 'ham', False),
    (['spam'], 'spam', True),
    (['spam'], 'spam.ham', False),
    (['spam'], 'eggs', False),
    (['spam*'], 'spam', True),
    (['spam*'], 'spam.ham', True),
    (['spam*'], 'eggs', False),
    (['spam'], '/spam', True),
])
def test_ignorer(monkeypatch, tmp_path: Path, ignore_cfg, candidate, result) -> None:
    monkeypatch.setattr(os.path, 'relpath', lambda s: s.lstrip('/'))
    ignorer = common.ignorer(ignore_cfg)
    assert ignorer(candidate) == result


def test_find_required_modules(tmp_path: Path) -> None:
    class options:
        skip_incompatible = False

    options.ignore_reqs = common.ignorer(ignore_cfg=['barfoo'])

    fake_requirements_file = tmp_path / 'requirements.txt'
    fake_requirements_file.write_text('foobar==1\nbarfoo==2')

    reqs = common.find_required_modules(
        options=options,
        requirements_filename=str(fake_requirements_file),
    )
    assert reqs == set(['foobar'])


def test_find_required_modules_env_markers(tmp_path) -> None:
    class options:
        skip_incompatible = True

        def ignore_reqs(self, modname) -> bool:
            return False

    fake_requirements_file = tmp_path / 'requirements.txt'
    fake_requirements_file.write_text('spam==1; python_version<"2.0"\n'
                                      'ham==2;\n'
                                      'eggs==3\n')

    reqs = common.find_required_modules(
        options=options(),
        requirements_filename=str(fake_requirements_file),
    )
    assert reqs == {'ham', 'eggs'}


def test_find_imported_modules_sets_encoding_to_utf8_when_reading(tmp_path) -> None:
    (tmp_path / 'module.py').touch()

    class options:
        paths = [tmp_path]

        def ignore_files(*_) -> bool:
            return False

    expected_encoding = 'utf-8'
    used_encoding = None

    original_open = common.__builtins__['open']

    def mocked_open(*args, **kwargs) -> None:
        # As of Python 3.9, the args to open() are as follows:
        # file, mode, buffering, encoding, erorrs, newline, closedf, opener
        nonlocal used_encoding
        if 'encoding' in kwargs:
            used_encoding = kwargs['encoding']
        return original_open(*args, **kwargs)

    common.__builtins__['open'] = mocked_open
    common.find_imported_modules(options)
    common.__builtins__['open'] = original_open

    assert used_encoding == expected_encoding


def test_version_info_shows_version_number() -> None:
    assert __version__ in common.version_info()
