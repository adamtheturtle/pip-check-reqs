from setuptools import setup
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

with open(path.join(here, 'CHANGELOG.rst'), encoding='utf-8') as f:
    long_description += f.read()

# This is not usual, but this project needs both install_requires
# and requirements.txt and we'd like to not duplicate them
with open(path.join(here, 'requirements.txt'), encoding='utf-8') as f:
    requirements = [s.strip() for s in f.readlines()]

from pip_check_reqs import __version__

setup(
    name='pip_check_reqs',
    version=__version__,
    description=
        'Find packages that should or should not be in requirements for a '
        'project',
    long_description=long_description,
    url='https://github.com/r1chardj0n3s/pip-check-reqs',
    author='Richard Jonees',
    author_email='r1chardj0n3s@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
    ],
    packages=['pip_check_reqs'],
    entry_points={
        'console_scripts': [
            'pip-missing-reqs=pip_check_reqs.find_missing_reqs:main',
            'pip-extra-reqs=pip_check_reqs.find_extra_reqs:main',
        ],
    },
    install_requires=requirements
)
