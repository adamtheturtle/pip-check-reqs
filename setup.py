from __future__ import annotations

from pathlib import Path

from setuptools import setup

from pip_check_reqs import __version__

here = Path.resolve(Path(__file__).parent)


def _get_dependencies(requirements_file: Path) -> list[str]:
    """Return requirements from a requirements file.

    This expects a requirements file with no ``--find-links`` lines.
    """
    lines = requirements_file.read_text().strip().split("\n")
    return [line for line in lines if not line.startswith("#")]


readme = here / "README.rst"
readme_content = readme.read_text(encoding="utf-8")
changelog = here / "CHANGELOG.rst"
changelog_content = changelog.read_text(encoding="utf-8")
long_description = readme_content + "\n\n" + changelog_content

INSTALL_REQUIRES = _get_dependencies(
    requirements_file=Path("requirements.txt"),
)

DEV_REQUIRES = _get_dependencies(
    requirements_file=Path("test-requirements.txt"),
)

setup(
    name="pip_check_reqs",
    version=__version__,
    description=(
        "Find packages that should or should not be in requirements for a "
        "project"
    ),
    long_description=long_description,
    url="https://github.com/r1chardj0n3s/pip-check-reqs",
    author="Richard Jones",
    author_email="r1chardj0n3s@gmail.com",
    maintainer="Adam Dangoor",
    maintainer_email="adamdangoor@gmail.com",
    license="MIT",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8.0",
    packages=["pip_check_reqs"],
    entry_points={
        "console_scripts": [
            "pip-missing-reqs=pip_check_reqs.find_missing_reqs:main",
            "pip-extra-reqs=pip_check_reqs.find_extra_reqs:main",
        ],
    },
    install_requires=INSTALL_REQUIRES,
    extras_require={"dev": DEV_REQUIRES},
)
