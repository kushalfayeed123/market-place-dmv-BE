# app/core/storage.py
"""
S3-backed storage helper for the ``documents`` subsystem.

All boto3 calls are *synchronous* (boto3 is not async-capable).  They are
wrapped with ``run_in_threadpool`` at the call-site in ``service.py`` so the
async event loop is not blocked.

Public functions:
* ``build_key``           – deterministic S3 key generator.
* ``presign_upload``      – generate a presigned POST (enforces content-type
                            and content-length-range on browser uploads).
* ``presign_download``    – short-lived (300 s) presigned GET URL.
* ``inspect_object``      – fetch object metadata for validation.
* ``signature_matches``   – constant-time equality check for checksum headers.
* ``delete_object``       – delete a single object from S3.
* ``key_exists``          – head-object existence check.
* ``upload_file_from_bytes`` – upload an in-memory blob (used by the migration
                            script when copying files from local disk).
* ``guess_content_type``  – MIME-type guess with safe fallback.
* ``public_url_for``      – build a public CDN URL when configured.
"""

from __future__ import annotations

import hmac as _hmac
import logging
import mimetypes
import uuid
from typing import Any

import boto3
from botocore.client import Config

from app.core.config import settings

logger = logging.getLogger(__name__)


def _s3_client():
    """Return a lazily-created S3 client.

    ``boto3.client`` itself is cheap; the underlying HTTP connection pool is
    reused internally.  In tests, moto's ``mock_aws`` intercepts at the
    transport layer, so no real network call is ever made.
    """
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )


def build_key(
    merchant_id: str,
    purpose: str,
    original_filename: str,
) -> str:
    """
    Build a deterministic-yet-unique S3 key.

    Layout: ``<purpose>/<merchant_id>/<uuid4>.<ext>``

    The UUID makes the key unique even if the same original filename is
    uploaded twice.  ``purpose`` gives a human-readable prefix for console
    / CDN routing.
    """
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower().strip()
    return f"{purpose}/{merchant_id}/{uuid.uuid4().hex}{ext}"


def presign_upload(
    *,
    bucket: str,
    key: str,
    content_type: str,
    max_bytes: int,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Generate a presigned POST for browser-to-S3 direct upload.

    Returns a dict with ``url`` and ``fields`` suitable for an HTML form POST
    (or ``fetch`` with FormData).  The ``fields`` include an ACL, a
    content-type constraint, and a ``content-length-range`` policy that
    enforces the size limit at the S3 side.
    """
    client = _s3_client()
    if ttl_seconds is None:
        ttl_seconds = settings.S3_UPLOAD_URL_TTL_SECONDS

    response = client.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"acl": "private"},
        Conditions=[
            ["content-length-range", 1, max_bytes],
            ["eq", "$Content-Type", content_type],
        ],
        ExpiresIn=ttl_seconds,
    )
    return response


def presign_download(
    *,
    bucket: str,
    key: str,
    ttl_seconds: int | None = None,
) -> str:
    """
    Generate a short-lived presigned URL to download an object.

    The URL is never persisted — the caller gets it, fetches the object, and
    the link expires (default 300 s).
    """
    client = _s3_client()
    if ttl_seconds is None:
        ttl_seconds = settings.S3_DOWNLOAD_URL_TTL_SECONDS

    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl_seconds,
    )
    return url


def inspect_object(*, bucket: str, key: str) -> dict[str, Any] | None:
    """
    Fetch object metadata from S3 via ``head_object``.

    Returns the raw boto3 response dict, or ``None`` if the object does not
    exist (404 / NoSuchKey).
    """
    client = _s3_client()
    try:
        response = client.head_object(Bucket=bucket, Key=key)
        return response
    except client.exceptions.ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return None
        logger.warning("S3 head_object failed for %s/%s: %s", bucket, key, exc)
        return None


def signature_matches(expected: str | None, actual: str | None) -> bool:
    """Constant-time comparison of two ETag / checksum values."""
    if not expected or not actual:
        return False
    return _hmac.compare_digest(
        expected.strip().lower().encode("utf-8"),
        actual.strip().lower().encode("utf-8"),
    )


def delete_object(*, bucket: str, key: str) -> bool:
    """Delete an object from S3. Returns ``True`` on success."""
    client = _s3_client()
    try:
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except client.exceptions.ClientError as exc:
        logger.error("S3 delete_object failed for %s/%s: %s", bucket, key, exc)
        return False


def key_exists(*, bucket: str, key: str) -> bool:
    """Return ``True`` if *key* exists in *bucket*."""
    return inspect_object(bucket=bucket, key=key) is not None


def upload_file_from_bytes(
    *,
    bucket: str,
    key: str,
    data: bytes,
    content_type: str | None = None,
) -> bool:
    """
    Upload an in-memory byte payload to S3.

    Used by the migration script (and tests) to push local files or bytes
    into S3.
    """
    client = _s3_client()
    extra_args: dict[str, Any] = {}
    if content_type:
        extra_args["ContentType"] = content_type
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data, **extra_args)
        return True
    except client.exceptions.ClientError as exc:
        logger.error("S3 put_object failed for %s/%s: %s", bucket, key, exc)
        return False


def guess_content_type(filename: str, fallback: str = "application/octet-stream") -> str:
    """Guess the MIME type from a filename, with a safe fallback."""
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


def public_url_for(key: str) -> str:
    """
    Build a public CDN URL when ``S3_PUBLIC_BASE_URL`` is configured,
    otherwise return the raw key.
    """
    base = (
        settings.S3_PUBLIC_BASE_URL.rstrip("/")
        if settings.S3_PUBLIC_BASE_URL
        else ""
    )
    if base:
        return f"{base}/{key}"
    return key


def read_object_head(*, bucket: str, key: str, length: int = 512) -> bytes | None:
    """
    Download the first *length* bytes of an object from S3.

    Uses a ranged GET request so only a small prefix is transferred.
    Returns ``None`` if the object does not exist.
    """
    client = _s3_client()
    try:
        response = client.get_object(
            Bucket=bucket, Key=key, Range=f"bytes=0-{length - 1}"
        )
        return response["Body"].read()
    except client.exceptions.ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return None
        logger.warning("S3 get_object failed for %s/%s: %s", bucket, key, exc)
        return None

