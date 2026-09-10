# app/db/types.py
"""
Cross-dialect type aliases.

Maps PostgreSQL-specific SQLAlchemy types to dialect-agnostic equivalents so
the same models compile against both MySQL (local development) and PostgreSQL
(staging / production).

===========  ================================================================
Alias        Behavior
===========  ================================================================
UUID         SQLAlchemy 2.0 generic ``Uuid`` -- renders a native ``UUID`` on
             PostgreSQL and ``CHAR(32)`` (hex) on MySQL. The Python side
             still receives/expects ``uuid.UUID`` objects when
             ``as_uuid=True``.
BIGINT       ``BigInteger`` (both dialects).
CHAR         ``CHAR`` (both dialects).
CITEXT       PostgreSQL has a native case-insensitive ``CITEXT`` type; MySQL's
             default ``_ci`` collation is already case-insensitive, so a plain
             ``String`` behaves equivalently there.
ENUM         ``sqlalchemy.Enum`` -- creates a native ``ENUM`` on MySQL and a
             named enum on PostgreSQL. Labeled by the enum member *name* in
             both dialects.
===========  ================================================
"""

from sqlalchemy import (  # noqa: F401
    CHAR,
    BigInteger,
    Enum as SAEnum,
    String,
    Uuid,
)

UUID = Uuid
BIGINT = BigInteger
ENUM = SAEnum
# MySQL's default collation (case-insensitive) makes String behave like CITEXT.
CITEXT = String(255)