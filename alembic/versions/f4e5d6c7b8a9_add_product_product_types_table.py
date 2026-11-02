"""add product product types table

Revision ID: f4e5d6c7b8a9
Revises: b2c3d4e5f6a7
Create Date: 2026-10-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4e5d6c7b8a9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "product_product_types",
        sa.Column(
            "product_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "product_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("product_id", "product_type"),
    )
    op.create_index(
        "idx_product_product_types_product",
        "product_product_types",
        ["product_id"],
    )
    op.create_index(
        "idx_product_product_types_type",
        "product_product_types",
        ["product_type"],
    )

    # Backfill existing products from their single fulfillment_type so that
    # current listings keep appearing in their original section.
    op.execute(
        """
        INSERT INTO product_product_types (product_id, product_type)
        SELECT id, fulfillment_type
        FROM products
        WHERE fulfillment_type IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_product_product_types_type",
        table_name="product_product_types",
    )
    op.drop_index(
        "idx_product_product_types_product",
        table_name="product_product_types",
    )
    op.drop_table("product_product_types")
