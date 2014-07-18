pip-missing-reqs
================

Find packages that should be in requirements for a project.

Assuming your project follows a layout like the suggested `sample project`_::

    setup.py
    setup.cfg
    requirements.txt
    sample/__init__.py
    sample/sample.py
    sample/tests/test_sample.py

.. _`sample project`: https://packaging.python.org/en/latest/tutorial.html#creating-your-own-project

Basic usage, running in your project directory:

    <activate virtualenv for your project>
    pip-missing-reqs --ignore-files=sample/tests sample

This will find all imports in the code in "sample" and check that the
packages those modules belong to are in the requirements.txt file.


Sample tox.ini configuration
----------------------------

To make your life easier, copy something like this into your tox.ini:

    [pip-missing-reqs]
    deps=-rrequirements.txt
    commands=pip-missing-reqs --ignore-files=sample/tests sample


Excluding test files (or others) from this check
------------------------------------------------

Your test files will sometimes be present in the same directory as your
application source ("sample" in the above examples). The requirements for
those tests generally should not be in the requirements.txt file, and you
don't want this tool to generate false hits for those.

You may exclude those test files from your check using the --ignore-files
option.
