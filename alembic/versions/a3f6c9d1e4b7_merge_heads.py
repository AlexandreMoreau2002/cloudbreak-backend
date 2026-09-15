"""merge heads c2078c6539a6 and f2a3b4c5d6e7"""

from collections.abc import Sequence

revision: str = "a3f6c9d1e4b7"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

down_revision = ("c2078c6539a6", "f2a3b4c5d6e7")


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
