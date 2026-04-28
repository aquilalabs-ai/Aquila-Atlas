"""Aquila-Atlas — The Atlas of your codebase."""

import warnings

# pydantic.v1 (the pydantic-v1 compatibility shim) emits an unconditional
# UserWarning on Python ≥ 3.14. langchain-core imports it internally; suppress
# the noise until langchain-core removes the pydantic v1 dependency.
warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14",
    category=UserWarning,
)

__version__ = "0.1.0"
