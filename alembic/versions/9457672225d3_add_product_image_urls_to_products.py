"""add product image urls to products

Revision ID: 9457672225d3
Revises: 541724af8568
Create Date: 2026-10-04 19:23:26.524397

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9457672225d3'
down_revision: Union[str, Sequence[str], None] = '541724af8568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `urls` mirrors `attributes`: a Text column holding a JSON array string
    # (e.g. '["https://cdn/x.jpg"]') parsed with json.loads in the service
    # layer. DEFAULT '[]' backfills existing rows.
    op.add_column(
        "products",
        sa.Column(
            "urls",
            sa.Text(),
            nullable=False,
            server_default=sa.text("('[]')"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("products", "urls")
