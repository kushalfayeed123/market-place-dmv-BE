"""add digital assets table

Revision ID: c9d8e7f6a5b4
Revises: f4e5d6c7b8a9
Create Date: 2026-11-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, Sequence[str], None] = "f4e5d6c7b8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "digital_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "license_type",
            sa.Text(),
            server_default="n_downloads",
            nullable=False,
        ),
        sa.Column("max_downloads", sa.Integer(), server_default="5", nullable=False),
        sa.Column("expiry_days", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_digital_assets_product",
        "digital_assets",
        ["product_id"],
    )
    op.create_index(
        "idx_digital_assets_variant",
        "digital_assets",
        ["variant_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_digital_assets_variant", table_name="digital_assets")
    op.drop_index("idx_digital_assets_product", table_name="digital_assets")
    op.drop_table("digital_assets")
