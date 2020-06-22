Contributing
============

Release process
---------------

* Update the CHANGELOG on the master branch
* Update ``__version__`` in ``pip_check_reqs/__init__.py`` on the master branch.

Run the following steps:

.. code:: sh

   git checkout master && \
   git pull && \
   pip install twine && \
   pip install -r requirements.txt && \
   rm -rf build dist && \
   git status # There should be no uncommitted changes.  && \
   python setup.py sdist bdist_wheel  && \
   twine upload -r pypi dist/*
