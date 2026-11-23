"""add share_links table

Revision ID: bb52ad8a9374
Revises: c9d8e7f6a5b4
Create Date: 2026-11-23 07:46:25.269493

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bb52ad8a9374'
down_revision: Union[str, Sequence[str], None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('share_links',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('merchant_id', sa.Uuid(), nullable=False),
    sa.Column('store_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('product_ids', sa.Text(), server_default=sa.text("('[]')"), nullable=False),
    sa.Column('is_active', sa.String(length=8), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_share_links_code')
    )
    op.create_index('idx_share_links_merchant', 'share_links', ['merchant_id'], unique=False)
    op.create_index('idx_share_links_store', 'share_links', ['store_id'], unique=False)
    op.create_table('share_link_products',
    sa.Column('link_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['link_id'], ['share_links.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('link_id', 'product_id')
    )
    op.create_index('idx_share_link_products_product', 'share_link_products', ['product_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_share_link_products_product', table_name='share_link_products')
    op.drop_table('share_link_products')
    op.drop_index('idx_share_links_store', table_name='share_links')
    op.drop_index('idx_share_links_merchant', table_name='share_links')
    op.drop_table('share_links')