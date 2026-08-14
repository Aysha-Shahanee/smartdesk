"""Service package.

Keep package imports lightweight so importing one service module does not
eagerly load heavyweight dependencies from unrelated modules.
"""

__all__: list[str] = []
