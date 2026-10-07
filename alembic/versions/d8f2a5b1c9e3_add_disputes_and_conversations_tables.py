"""Add disputes and conversations tables

Revision ID: d8f2a5b1c9e3
Revises: c7f3a1b2d4e5
Create Date: 2026-10-07 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8f2a5b1c9e3"
down_revision: Union[str, Sequence[str], None] = "c7f3a1b2d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- disputes table ---
    op.create_table(
        "disputes",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("order_number", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False, server_default="NGN"),
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
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
        sa.CheckConstraint("amount >= 0", name="ck_disputes_amount_non_negative"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_disputes_merchant", "disputes", ["merchant_id"], unique=False)
    op.create_index("idx_disputes_status", "disputes", ["status"], unique=False)
    op.create_index(op.f("ix_disputes_order_id"), "disputes", ["order_id"], unique=False)

    # --- conversations table ---
    op.create_table(
        "conversations",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="unread"),
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
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_conversations_merchant", "conversations", ["merchant_id"], unique=False
    )
    op.create_index(
        "idx_conversations_status", "conversations", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_conversations_order_id"), "conversations", ["order_id"], unique=False
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # Drop child tables first (FK constraints).
    op.drop_index(op.f("ix_conversations_order_id"), table_name="conversations")
    op.drop_index("idx_conversations_status", table_name="conversations")
    op.drop_index("idx_conversations_merchant", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index(op.f("ix_disputes_order_id"), table_name="disputes")
    op.drop_index("idx_disputes_status", table_name="disputes")
    op.drop_index("idx_disputes_merchant", table_name="disputes")
    op.drop_table("disputes")
    # ### end Alembic commands ###
