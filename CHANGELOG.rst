Release History
---------------

1.1.2
- corrected version of vendored search_packages_info() from pip
- handle relative imports
- fix program to generate exit code useful for testing

1.1.1
- fixed handling of import from __future__
- self-tested and added own requirements.txt
- cleaned up usage to require a file or directory to scan (rather than
  defaulting to ".")
- vendored code from pip 1.6dev which fixes bug in search_packages_info
  until pip 1.6 is released

1.1.0 
- implemented --ignore-module
