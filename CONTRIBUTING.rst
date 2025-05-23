Contributing
============

Release process
---------------

* Update the CHANGELOG on the master branch
* Update ``__version__`` in ``pip_check_reqs/__init__.py`` on the master branch.

Run the following steps, entering a PyPI API token when prompted:

.. code:: sh

   git checkout master && \
   git pull && \
   pip install --upgrade twine build && \
   pip install -r requirements.txt && \
   rm -rf build dist && \
   git status # There should be no uncommitted changes.  && \
   python -m build && \
   twine upload --username=__token__ -r pypi dist/*
