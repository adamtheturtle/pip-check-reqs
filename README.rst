|Build Status| |PyPI|

.. |Build Status| image:: https://github.com/r1chardj0n3s/pip-check-reqs/workflows/CI/badge.svg
   :target: https://github.com/r1chardj0n3s/pip-check-reqs/actions
.. |PyPI| image:: https://badge.fury.io/py/pip-check-reqs.svg
   :target: https://badge.fury.io/py/pip-check-reqs

pip-check-reqs
==============

It happens: you start using a module in your project and it works and you
don't realise that it's only being included in your `virtualenv`_ because
it's a dependency of a package you're using. pip-missing-reqs finds those
modules so you can include them in the `requirements.txt`_ for the project.

Alternatively, you have a long-running project that has some packages in
requirements.txt that are no longer actively used in the codebase. The
pip-extra-reqs tool will find those modules so you can remove them.

.. _`virtualenv`: https://virtualenv.pypa.io/en/latest/
.. _`requirements.txt`: https://pip.pypa.io/en/latest/user_guide.html#requirements-files

Assuming your project follows a layout like the suggested sample project::

    setup.py
    setup.cfg
    requirements.txt
    sample/__init__.py
    sample/sample.py
    sample/tests/test_sample.py

Basic usage, running in your project directory::

    <activate virtualenv for your project>
    pip-missing-reqs --ignore-file=sample/tests/* sample

This will find all imports in the code in "sample" and check that the
packages those modules belong to are in the requirements.txt file.

If dependencies are split across multiple files, repeat ``--requirements-file``
to check them together::

    pip-missing-reqs --requirements-file=requirements.txt \
        --requirements-file=test-requirements.txt sample

Additionally it is possible to check that there are no dependencies in
requirements.txt that are then unused in the project::

    <activate virtualenv for your project>
    pip-extra-reqs --ignore-file=sample/tests/* sample

This would find anything that is listed in requirements.txt but that is not
imported by sample.

``pip-missing-reqs`` learns which requirement provides a module from the
installed distribution, so an import of a module which is not installed
cannot be traced to a requirement. It warns about each such import, giving
the file and line, rather than passing over it. Silence a warning with
``--ignore-module`` if the import is conditional, or if the module comes
from a path which you do not give to ``pip-missing-reqs``.

An import in a ``try`` block which catches ``ImportError`` is a soft
dependency: the code runs whether or not the module is installed.
``pip-missing-reqs`` does not warn about such an import when the module is
not installed::

    try:
        import Levenshtein
    except ImportError:
        Levenshtein = None

``pip-extra-reqs`` learns which modules a requirement provides from the
installed distribution, so it cannot check a requirement which is not
installed in the environment. It warns about each such requirement rather
than reporting it as extra.

A requirement installed in editable mode, with ``pip install -e``, imports
its modules from the directory it is installed from rather than from a copy
in ``site-packages``. Both commands read that directory from the install, so
an editable requirement is checked as any other requirement is. The source
you give to the commands is the project being checked rather than a
requirement of it, so a module of that source is not treated as a
requirement even when the project itself is installed in editable mode.

A requirement given as a URL or a directory, such as ``-e .`` or
``git+https://github.com/org/repo.git``, does not name a distribution. When
the requirement is installed, both commands take the name from the install,
which records where it came from. Otherwise, name the distribution with an
``#egg=<name>`` fragment.

Sample tox.ini configuration
----------------------------

To make your life easier, copy something like this into your tox.ini::

    [testenv:pip-check-reqs]
    deps=-rrequirements.txt
    commands=
        pip-missing-reqs --ignore-file=sample/tests/* sample
        pip-extra-reqs --ignore-file=sample/tests/* sample


Excluding test files (or others) from this check
------------------------------------------------

Your test files will sometimes be present in the same directory as your
application source ("sample" in the above examples). The requirements for
those tests generally should not be in the requirements.txt file, and you
don't want this tool to generate false hits for those.

You may exclude those test files from your check using the ``--ignore-file``
option (shorthand is ``-f``). Multiple instances of the option are allowed.

A virtual environment within the checked directory is skipped automatically.
A directory is treated as a virtual environment when it contains a
``pyvenv.cfg`` file, which ``venv``, ``virtualenv`` and ``uv`` all create.

Files which Git ignores can be skipped too, with ``--use-gitignore`` (shorthand
is ``-g``)::

    pip-missing-reqs --use-gitignore sample
    pip-extra-reqs --use-gitignore sample

Each ``.gitignore`` file from the repository root down to the checked
directory applies, as it does in Git. A file or directory which one ignores
is not scanned. A file given directly on the command line is always scanned.


Excluding modules from the check
--------------------------------

If your project has modules which are conditionally imported, or requirements
which are conditionally included, you may exclude certain modules from the
check by name (or glob pattern) using ``--ignore-module`` (shorthand is ``-m``)::

    # ignore the module spam
    pip-missing-reqs --ignore-module=spam sample
    # ignore the whole package spam as well
    pip-missing-reqs --ignore-module=spam --ignore-module=spam.* sample


Excluding requirements from the check
-------------------------------------

A project may need a requirement which its code never imports. A web
application which lists ``gunicorn`` to serve it, or a plugin which is
loaded by an entry point, is installed and used without an ``import``
statement. ``pip-extra-reqs`` reports such a requirement as extra.

You may exclude a requirement from the check by name (or glob pattern) using
``--ignore-requirement`` (shorthand is ``-r``). The name is matched as it is
written in the requirements file. Multiple instances of the option are
allowed::

    # ignore the requirement gunicorn
    pip-extra-reqs --ignore-requirement=gunicorn sample
    # ignore every requirement whose name starts with pytest
    pip-extra-reqs --ignore-requirement=pytest --ignore-requirement=pytest-* sample


Checking transitive dependencies
--------------------------------

``pip-missing-reqs`` only looks for the requirements which the source imports.
A dependency of one of those, which the source does not import itself, need
not be listed.

Some files must list every distribution, whether the source imports it or
not. A constraints file, given to pip with ``-c``, which pins a minimum
version of every distribution in a test environment is one. To check such a
file, pass ``--transitive`` (shorthand is ``-t``). The dependencies of each
distribution the source imports are then followed, recursively, and any
which is not listed is reported with the distribution which requires it::

    pip-missing-reqs --requirements-file=minimum-constraints.txt --transitive sample

A dependency is only followed when its environment marker holds in the
environment which ``pip-missing-reqs`` runs in, and a dependency of an extra
is only followed when that extra is asked for.


Using pyproject.toml instead of requirements.txt
------------------------------------------------

If your project uses ``pyproject.toml``, there are multiple ways to use ``pip-check-reqs`` with it.

The simplest way is to give the ``pyproject.toml`` file as the requirements file.
The ``dependencies`` list of its ``[project]`` table is then checked::

    pip-missing-reqs --requirements-file pyproject.toml src
    pip-extra-reqs --requirements-file pyproject.toml src

Optional dependencies and other tables are not read.
For those, one way is to use an external tool to convert ``pyproject.toml`` to ``requirements.txt``::

    # requires `pip install pdm`
    pdm export --pyproject > requirements.txt

    # or, if you prefer uv, `pip install uv`
    uv pip compile --no-deps pyproject.toml > requirements.txt

Then you can use ``pip-missing-reqs`` and ``pip-extra-reqs`` as usual.

Another way is to use a ``requirements.txt`` file within your ``pyproject.toml`` file,
for example with the ``setuptools`` build backend:

.. code:: toml

   [build-system]
   build-backend = "setuptools.build_meta"
   requires = [
     "setuptools",
   ]

   [project]
   ...
   dynamic = ["dependencies"]

   [tool.setuptools.dynamic]
   dependencies = { file = "requirements.txt" }


Comparison with deptry
----------------------

`deptry`_ is another tool which finds missing and unused dependencies.
It overlaps with ``pip-check-reqs``, and differs in ways which may decide
which one suits a project.

- ``deptry`` reads dependencies from ``pyproject.toml`` directly, whether
  they follow PEP 621 or the Poetry or PDM format, as well as from
  requirements files. ``pip-check-reqs`` reads requirements files only, so a
  project which declares its dependencies in ``pyproject.toml`` must first
  export them to a requirements file.
- ``deptry`` runs more checks. As well as missing and unused dependencies,
  it reports an import of a development dependency from non-development
  code, an import of a standard library module which is listed as a
  dependency, and an import of a transitive dependency which is not declared.
  ``pip-check-reqs`` reports missing and extra requirements, and can check
  that a file lists every transitive dependency with ``--transitive``.
- ``deptry`` guesses the module name of a dependency which is not installed
  by translating the distribution name, so it can run against an incomplete
  environment at the cost of some accuracy. ``pip-check-reqs`` reads the
  installed distribution only, and warns about each import or requirement it
  cannot find.
- ``deptry`` is configured in ``pyproject.toml`` and supports inline
  ``# deptry: ignore`` comments. ``pip-check-reqs`` is configured on the
  command line only.
- ``deptry`` has a core written in Rust and is faster on a large codebase.
  ``pip-check-reqs`` uses internals of ``pip`` which may change between
  ``pip`` releases.

For a new project, ``deptry`` is likely the better choice. ``pip-check-reqs``
remains a good fit for a project which manages its dependencies with
requirements files, or which needs the ``--transitive`` check.

.. _`deptry`: https://github.com/fpgmaas/deptry


With Thanks To
--------------

Josh Hesketh -- who refactored code and contributed the pip-extra-reqs tool.

Wil Cooley -- who handled the removal of normalize_name and fixed some bugs.
