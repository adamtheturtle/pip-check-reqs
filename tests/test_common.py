from __future__ import absolute_import

import ast
import logging
import os.path
from pathlib import Path

import pytest
import pretend

from pip_check_reqs import common


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
def test_is_package_file(path, result):
    assert common.is_package_file(path) == result


def test_FoundModule():
    fm = common.FoundModule('spam', 'ham')
    assert fm.modname == 'spam'
    assert fm.filename == os.path.realpath('ham')
    assert fm.locations == []
    assert str(fm) == 'FoundModule("spam")'


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
def test_ImportVisitor(stmt, result):
    class options:
        def ignore_mods(self, modname):
            return False

    vis = common.ImportVisitor(options())
    vis.set_location('spam.py')
    vis.visit(ast.parse(stmt))
    result = vis.finalise()
    assert set(result.keys()) == set(result)


def test_pyfiles_file(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam/ham.py'))

    assert list(common.pyfiles('spam')) == ['/spam/ham.py']


def test_pyfiles_file_no_dice(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam/ham'))

    with pytest.raises(ValueError):
        list(common.pyfiles('spam'))


def test_pyfiles_package(monkeypatch):
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


@pytest.mark.parametrize(["ignore_ham", "ignore_hashlib", "expect", "locs"], [
    (False, False, ['ast', 'os', 'hashlib'], [('spam.py', 2), ('ham.py', 2)]),
    (False, True, ['ast', 'os'], [('spam.py', 2), ('ham.py', 2)]),
    (True, False, ['ast'], [('spam.py', 2)]),
    (True, True, ['ast'], [('spam.py', 2)]),
])
def test_find_imported_modules(monkeypatch, caplog, ignore_ham, ignore_hashlib,
                               expect, locs):
    monkeypatch.setattr(common, 'pyfiles',
                        pretend.call_recorder(lambda x: ['spam.py', 'ham.py']))

    class FakeFile():
        contents = [
            'from os import path\nimport ast, hashlib',
            'from __future__ import braces\nimport ast, sys\n'
            'from . import friend',
        ]

        def __init__(self, filename):
            pass

        def read(self):
            return self.contents.pop()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(common, 'open', FakeFile, raising=False)

    caplog.set_level(logging.INFO)

    class options:
        paths = ['dummy']
        verbose = True

        @staticmethod
        def ignore_files(path):
            if path == 'ham.py' and ignore_ham:
                return True
            return False

        @staticmethod
        def ignore_mods(module):
            if module == 'hashlib' and ignore_hashlib:
                return True
            return False

    result = common.find_imported_modules(options)
    assert set(result) == set(expect)
    assert result['ast'].locations == locs

    if ignore_ham:
        assert caplog.records[0].message == 'ignoring: ham.py'


@pytest.mark.parametrize(["files","expect"], [
    (['utf8.py'],['ast', 'os', 'hashlib']),
    (['gbk.py'],['ast', 'os', 'hashlib'])
])
def test_find_imported_modules_charset(monkeypatch, caplog,
       files, expect):
    monkeypatch.setattr(common, 'pyfiles',
        pretend.call_recorder(lambda x: files))

    if sys.version_info[0] == 2:
        # py2 will find sys module but py3k won't
        expect.append('sys')



    caplog.set_level(logging.INFO)

    class options:
        paths = ['.']
        verbose = True

        @staticmethod
        def ignore_files(path):
            return False

        @staticmethod
        def ignore_mods(module):
            return False

    result = common.find_imported_modules(options)
    assert set(result) == set(expect)


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
def test_ignorer(monkeypatch, tmp_path: Path, ignore_cfg, candidate, result):
    monkeypatch.setattr(os.path, 'relpath', lambda s: s.lstrip('/'))
    ignorer = common.ignorer(ignore_cfg)
    assert ignorer(candidate) == result


def test_find_required_modules(monkeypatch, tmp_path: Path):
    class options:
        pass

    options.ignore_reqs = common.ignorer(ignore_cfg=['barfoo'])

    fake_requirements_file = tmp_path / 'requirements.txt'
    fake_requirements_file.write_text('foobar==1\nbarfoo==2')

    reqs = common.find_required_modules(
        options=options,
        requirements_filename=str(fake_requirements_file),
    )
    assert reqs == set(['foobar'])
