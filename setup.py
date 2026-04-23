import os

from setuptools import setup

if os.getenv("READTHEDOCS", False):
    setup(python_requires=">=3.10.0")
else:
    # Metadata and options defined in setup.cfg
    setup(include_package_data=True)
