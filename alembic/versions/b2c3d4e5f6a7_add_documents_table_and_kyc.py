"""add documents table and kyc_document_id to merchants

Revision ID: b2c3d4e5f6a7
Revises: 7a3b1c9d2e4f
Create Date: 2026-10-20 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "7a3b1c9d2e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # --- documents table ---
    # Mirrors backend/app/models/document.py (Document model + BaseModel columns)
    # The documents table was missing from the DB even though the model and
    # DocumentService reference it (e.g. PURPOSE_TARGETS KYC -> merchants.kyc_document_id).
    if "documents" not in existing_tables:
        op.create_table(
            "documents",
            sa.Column("purpose", sa.String(length=64), nullable=False,
                      comment="What kind of document this is (kyc, product_image, …)"),
            sa.Column("merchant_id", sa.Uuid(), nullable=True,
                      comment="Owning merchant (NULL for user-scoped or platform docs)."),
            sa.Column("filename", sa.Text(), nullable=False,
                      comment="Original filename supplied by the client."),
            sa.Column("content_type", sa.Text(), nullable=False,
                      comment="MIME type declared at upload."),
            sa.Column("size_bytes", sa.Integer(), nullable=False,
                      comment="File size in bytes, checked at completion."),
            sa.Column("object_key", sa.Text(), nullable=False,
                      comment="S3 object key."),
            sa.Column("status", sa.String(length=32), nullable=False,
                      server_default="pending",
                      comment="pending → complete → cleanup"),
            sa.Column("public", sa.Boolean(), nullable=False,
                      server_default="0",
                      comment="If True, served via public CDN URL; else presigned download."),
            sa.Column("deleted_at", sa.Text(), nullable=True,
                      comment="Soft-delete timestamp (UTC ISO)."),
            sa.Column("related_type", sa.String(length=64), nullable=True,
                      comment="e.g. Product, Merchant, Store, User"),
            sa.Column("related_id", sa.Uuid(), nullable=True,
                      comment="FK to related_type PK (no hard FK constraint)."),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="SET NULL"),
        )
        # MySQL requires a prefix length for indexes on TEXT columns.
        # object_key is TEXT, so we use a 255-char prefix for the unique index.
        op.execute("CREATE UNIQUE INDEX uq_documents_object_key ON documents (object_key(255))")
        op.create_index("idx_documents_merchant_purpose", "documents",
                        ["merchant_id", "purpose"], unique=False)
        op.create_index("idx_documents_related", "documents",
                        ["related_type", "related_id"], unique=False)
        op.create_index("idx_documents_status_created", "documents",
                        ["status", "created_at"], unique=False)
        op.create_index("ix_documents_merchant_id", "documents",
                        ["merchant_id"], unique=False)
        op.create_index("ix_documents_related_id", "documents",
                        ["related_id"], unique=False)

    # --- kyc_document_id on merchants ---
    # Mirrors backend/app/models/merchant.py — was added to the model but
    # never had a migration, causing "Unknown column 'merchants.kyc_document_id'".
    existing_cols = {c["name"] for c in inspector.get_columns("merchants")}
    if "kyc_document_id" not in existing_cols:
        op.add_column(
            "merchants",
            sa.Column("kyc_document_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_merchants_kyc_document_id_documents",
            "merchants", "documents",
            ["kyc_document_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop FK + column before dropping documents table
    if "merchants" in existing_tables:
        fk_constraint = "fk_merchants_kyc_document_id_documents"
        # Check if the FK exists
        fks = inspector.get_foreign_keys("merchants")
        if any(fk.get("name") == fk_constraint for fk in fks):
            op.drop_constraint(fk_constraint, "merchants", type_="foreignkey")
        existing_cols = {c["name"] for c in inspector.get_columns("merchants")}
        if "kyc_document_id" in existing_cols:
            op.drop_column("merchants", "kyc_document_id")

    # Drop documents table
    if "documents" in existing_tables:
        op.execute("DROP INDEX uq_documents_object_key ON documents")
        op.drop_index("ix_documents_related_id", table_name="documents")
        op.drop_index("ix_documents_merchant_id", table_name="documents")
        op.drop_index("idx_documents_status_created", table_name="documents")
        op.drop_index("idx_documents_related", table_name="documents")
        op.drop_index("idx_documents_merchant_purpose", table_name="documents")
        op.drop_table("documents")
