"""add delivery_address to orders

Revision ID: 7a3b1c9d2e4f
Revises: f2c3d4e5f6a7
Create Date: 2026-10-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7a3b1c9d2e4f"
down_revision = "f2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("delivery_address", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "delivery_address")
