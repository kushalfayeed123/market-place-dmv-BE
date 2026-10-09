# app/models/product_like.py
"""Product like / favorite model — tracks which users like which products."""

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from app.db.base import BaseModel
from app.db.types import UUID


class ProductLike(BaseModel):
    __tablename__ = "product_likes"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_product_likes_user_product"),
        Index("idx_product_likes_product", product_id),
        Index("idx_product_likes_user", user_id),
    )

    def __repr__(self):
        return f"<ProductLike(user_id={self.user_id}, product_id={self.product_id})>"