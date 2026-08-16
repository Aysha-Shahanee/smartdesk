"""Bridge the pre-merge local schema into the current migration chain.

Revision ID: 4ba685c05c0b
Revises: 0004_remove_ide_foreground_sec_terminal_debug_counts

The legacy SmartDesk database was stamped with this revision before the
current dev migration history was merged. Its core session schema is
structurally equivalent to current revision 0004. The legacy database also
contains additive GitHub tables and retired minute-window tables; those are
handled non-destructively by later compatibility-aware migrations.
"""

from typing import Sequence, Union


revision: str = "4ba685c05c0b"
down_revision: Union[str, Sequence[str], None] = (
    "0004_remove_ide_foreground_sec_terminal_debug_counts"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema validation was used to establish the 0004 equivalence. This is a
    # history bridge only; it must not rewrite or discard legacy data.
    pass


def downgrade() -> None:
    pass
