"""Add password reset token columns to users

Revision ID: a1b2c3d4e5f6
Revises: e5f6a7b8c9d0
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    users_cols = {c["name"] for c in inspector.get_columns("users")}

    if "password_reset_token_hash" not in users_cols:
        op.add_column("users", sa.Column("password_reset_token_hash", sa.Text(), nullable=True))

    if "password_reset_expires_at" not in users_cols:
        op.add_column(
            "users",
            sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    users_cols = {c["name"] for c in inspector.get_columns("users")}

    if "password_reset_expires_at" in users_cols:
        op.drop_column("users", "password_reset_expires_at")

    if "password_reset_token_hash" in users_cols:
        op.drop_column("users", "password_reset_token_hash")
