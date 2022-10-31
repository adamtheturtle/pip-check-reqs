|Build Status| |codecov| |PyPI|

.. |Build Status| image:: https://github.com/r1chardj0n3s/pip-check-reqs/workflows/CI/badge.svg
   :target: https://github.com/r1chardj0n3s/pip-check-reqs/actions
.. |codecov| image:: https://codecov.io/gh/r1chardj0n3s/pip-check-reqs/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/r1chardj0n3s/pip-check-reqs
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

Additionally it is possible to check that there are no dependencies in
requirements.txt that are then unused in the project::

    <activate virtualenv for your project>
    pip-extra-reqs --ignore-file=sample/tests/* sample

This would find anything that is listed in requirements.txt but that is not
imported by sample.

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

You may exclude those test files from your check using the `--ignore-file`
option (shorthand is `-f`). Multiple instances of the option are allowed.


Excluding modules from the check
--------------------------------

If your project has modules which are conditionally imported, or requirements
which are conditionally included, you may exclude certain modules from the
check by name (or glob pattern) using `--ignore-module` (shorthand is `-m`)::

    # ignore the module spam
    pip-missing-reqs --ignore-module=spam sample
    # ignore the whole package spam as well
    pip-missing-reqs --ignore-module=spam --ignore-module=spam.* sample


With Thanks To
--------------

Josh Hesketh -- who refactored code and contributed the pip-extra-reqs tool.

Wil Cooley -- who handled the removal of normalize_name and fixed some bugs.
