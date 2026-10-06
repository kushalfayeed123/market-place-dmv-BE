"""Add notifications table and order_number to orders

Revision ID: c7f3a1b2d4e5
Revises: 9457672225d3
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f3a1b2d4e5"
down_revision: Union[str, Sequence[str], None] = "9457672225d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- orders: add order_number (human-readable, unique) ---
    op.add_column(
        "orders",
        sa.Column(
            "order_number",
            sa.String(length=50),
            nullable=False,
            server_default="ORD-PENDING",
        ),
    )
    op.create_index(
        "idx_orders_order_number", "orders", ["order_number"], unique=True
    )
    # Remove the placeholder server_default so future inserts rely on the app.
    op.alter_column("orders", "order_number", server_default=None)

    # --- notifications table ---
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default="email",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("related_order_id", sa.Uuid(), nullable=True),
        sa.Column("related_payment_id", sa.Uuid(), nullable=True),
        sa.Column("related_product_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "payload",
            sa.Text(),
            nullable=True,
            server_default="{}",
        ),
        sa.Column("cost_units", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "cost_units >= 0", name="ck_notifications_cost_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["related_order_id"], ["orders.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["related_payment_id"],
            ["payment_transactions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["related_product_id"], ["products.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_notifications_user_status",
        "notifications",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_notifications_merchant_status",
        "notifications",
        ["merchant_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_notifications_type", "notifications", ["type"], unique=False
    )
    op.create_index(
        "idx_notifications_created_at",
        "notifications",
        [sa.literal_column("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_notifications_created_at", table_name="notifications")
    op.drop_index("idx_notifications_type", table_name="notifications")
    op.drop_index(
        "idx_notifications_merchant_status", table_name="notifications"
    )
    op.drop_index(
        "idx_notifications_user_status", table_name="notifications"
    )
    op.drop_table("notifications")

    op.drop_index("idx_orders_order_number", table_name="orders")
    op.drop_column("orders", "order_number")
