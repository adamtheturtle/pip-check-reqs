Contributing
============

Release process
---------------

* Update the CHANGELOG on the master branch.
* Update ``__version__`` in ``pip_check_reqs/__init__.py`` on the master branch.

Run the release script, entering a PyPI API token when prompted:

.. code:: sh

   ./release.sh
