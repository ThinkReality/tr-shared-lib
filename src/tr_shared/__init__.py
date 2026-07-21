"""tr_shared — shared platform library.

``__version__`` is single-sourced from the installed package metadata (i.e.
pyproject ``[project].version``) so the two can never drift.
"""

from importlib.metadata import version

__version__ = version("tr-shared-lib")
