"""Add payouts table

Revision ID: e5f6a7b8c9d0
Revises: d8f2a5b1c9e3
Create Date: 2026-10-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d8f2a5b1c9e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- idempotency guard: skip if table already exists ---
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()
    if "payouts" in existing_tables:
        return

    # --- payouts table ---
    # Mirrors backend/app/models/payout.py (Payout model + BaseModel columns)
    op.create_table(
        "payouts",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="requested"),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("bank_account_last4", sa.String(length=10), nullable=True),
        sa.Column("bank_name", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        # Columns inherited from BaseModel
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name="ck_payouts_amount_non_negative"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_payouts_reference"),
    )
    op.create_index("idx_payouts_merchant", "payouts", ["merchant_id"], unique=False)
    op.create_index("idx_payouts_status", "payouts", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()
    if "payouts" not in existing_tables:
        return

    op.drop_index("idx_payouts_status", table_name="payouts")
    op.drop_index("idx_payouts_merchant", table_name="payouts")
    op.drop_constraint("uq_payouts_reference", "payouts", type_="unique")
    op.drop_table("payouts")
