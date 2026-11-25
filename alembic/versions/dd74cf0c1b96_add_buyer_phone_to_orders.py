"""add buyer_phone to orders

Revision ID: dd74cf0c1b96
Revises: cc63be9b0a85
Create Date: 2026-11-25 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'dd74cf0c1b96'
down_revision: Union[str, Sequence[str], None] = 'cc63be9b0a85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('buyer_phone', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'buyer_phone')
