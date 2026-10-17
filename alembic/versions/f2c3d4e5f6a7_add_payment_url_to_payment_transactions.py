"""add payment_url to payment_transactions

Revision ID: f2c3d4e5f6a7
Revises: e1b27b0f76d4
Create Date: 2026-10-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "e1b27b0f76d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add payment_url column — mirrors the model in app/models/payment_transaction.py
    op.add_column("payment_transactions", sa.Column("payment_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("payment_transactions", "payment_url")
