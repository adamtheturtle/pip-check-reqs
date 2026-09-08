Contributing
============

Setting up a development environment
------------------------------------

Install the project and its development dependencies with `uv`_:

.. code-block:: console

   $ uv sync --extra dev

Pylint's spelling checker requires the ``enchant`` C library.
Install it on macOS with `Homebrew`_:

.. code-block:: console

   $ brew install enchant

and on Ubuntu with ``apt``:

.. code-block:: console

   $ apt-get install -y enchant

Install ``prek`` hooks:

.. code-block:: console

   $ uv run --extra dev prek install

.. _uv: https://docs.astral.sh/uv/
.. _Homebrew: https://brew.sh

Linting
-------

Run lint tools either by committing, or with:

.. code-block:: console

   $ uv run --extra dev prek run --all-files --hook-stage pre-commit --verbose
   $ uv run --extra dev prek run --all-files --hook-stage pre-push --verbose
   $ uv run --extra dev prek run --all-files --hook-stage manual --verbose

Running tests
-------------

Run ``pytest``:

.. code-block:: console

   $ uv run --extra dev pytest

Continuous integration
----------------------

Tests and lint checks run on GitHub Actions.
The configuration for this is in ``.github/workflows/``.

Release process
---------------

* Update the CHANGELOG on the master branch.
* Update ``__version__`` in ``pip_check_reqs/__init__.py`` on the master branch.

Run the release script, entering a PyPI API token when prompted:

.. code:: sh

   ./release.sh
