"""add recipient_code to merchant_payout_accounts

Revision ID: cc63be9b0a85
Revises: bb52ad8a9374
Create Date: 2026-11-24 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cc63be9b0a85'
down_revision: Union[str, Sequence[str], None] = 'bb52ad8a9374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'merchant_payout_accounts',
        sa.Column('recipient_code', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('merchant_payout_accounts', 'recipient_code')
