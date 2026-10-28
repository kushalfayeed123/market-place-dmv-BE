# app/tests/test_documents.py
"""
Tests for the documents subsystem.

These tests mock S3 with moto (``mock_aws``) and use the in-memory SQLite
test database provided by ``app/tests/conftest.py``.  They exercise the
``DocumentService`` directly (no HTTP/auth layer), which keeps them fast
and focused on the upload / complete / retrieval / domain-linking logic.
"""

from __future__ import annotations

import json
import uuid

import pytest
from moto import mock_aws

from app.core.config import settings
from app.core.storage import (
    build_key,
    delete_object,
    inspect_object,
    presign_upload,
    public_url_for,
    upload_file_from_bytes,
)
from app.models.document import Document
from app.models.enums import DocumentPurpose, DocumentStatus
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.store import Store
from app.models.user import User, UserRole, UserStatus, Gender
from app.modules.documents.service import DocumentService, _check_magic
from app.schemas.document import (
    DocumentCompleteRequest,
    DocumentUploadRequest,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def s3_mock():
    """Spin up moto's S3 mock for every test in this module."""
    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name=settings.AWS_REGION)
        # moto requires CreateBucketConfiguration for non-us-east-1 regions
        if settings.AWS_REGION == "us-east-1":
            client.create_bucket(Bucket=settings.S3_BUCKET)
        else:
            client.create_bucket(
                Bucket=settings.S3_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION},
            )
        yield


@pytest.fixture
async def test_user(db) -> User:
    """Create a test user (merchant owner)."""
    from app.core.security import get_password_hash

    user = User(
        email="merchant@example.com",
        password_hash=get_password_hash("password123"),
        role=UserRole.MERCHANT_OWNER,
        status=UserStatus.ACTIVE,
        gender=Gender.UNSET,
        phone="08012345678",
        first_name="Test",
        last_name="Merchant",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
async def test_merchant(db, test_user) -> Merchant:
    """Create a test merchant owned by *test_user*."""
    from app.models.commission_plan import CommissionPlan

    plan = CommissionPlan(
        name="default",
        percentage_bps=500,
        currency="NGN",
        is_default=True,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    merchant = Merchant(
        owner_user_id=test_user.id,
        business_name="Test Store Ltd",
        slug=f"test-{uuid.uuid4().hex[:8]}",
        kyc_status="verified",
        commission_plan_id=plan.id,
    )
    db.add(merchant)
    await db.commit()
    await db.refresh(merchant)
    return merchant


@pytest.fixture
async def test_product(db, test_merchant) -> Product:
    """Create a test product under *test_merchant*."""
    store = Store(
        merchant_id=test_merchant.id,
        name="Main Store",
        slug=f"store-{uuid.uuid4().hex[:8]}",
    )
    db.add(store)
    await db.commit()
    await db.refresh(store)

    from app.models.category import Category

    cat = Category(name="Electronics")
    db.add(cat)
    await db.commit()
    await db.refresh(cat)

    product = Product(
        merchant_id=test_merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Test Widget",
        slug=f"widget-{uuid.uuid4().hex[:8]}",
        fulfillment_type="physical",
        status="active",
        base_price_amount=5000,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@pytest.fixture
async def service(db) -> DocumentService:
    """Return a DocumentService bound to the test session."""
    return DocumentService(db)


# ── Tests ─────────────────────────────────────────────────────────────────


class TestCheckMagic:
    """Unit tests for the _check_magic helper."""

    def test_png_signature_matches(self):
        png_header = b"\x89PNG\r\n\x1a\n"
        assert _check_magic("image/png", png_header) is True

    def test_png_signature_mismatch(self):
        fake_header = b"NOTAPNGFILE!!!"
        assert _check_magic("image/png", fake_header) is False

    def test_unknown_content_type_passes(self):
        assert _check_magic("application/x-custom", b"whatever") is True


class TestPresignedUpload:
    """Tests for DocumentService.create_presigned_upload."""

    @pytest.mark.asyncio
    async def test_presigned_upload_creates_pending_document(
        self, service, test_merchant, db
    ):
        """A presigned upload call should create a PENDING Document row."""
        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        response = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        assert response.document_id is not None
        assert response.upload_url is not None
        assert response.key.startswith("product_image/")
        assert response.max_size_bytes == settings.S3_MAX_UPLOAD_MB * 1024 * 1024
        assert response.ttl_seconds == settings.S3_UPLOAD_URL_TTL_SECONDS

        # Verify the DB row
        doc = await db.get(Document, uuid.UUID(response.document_id))
        assert doc is not None
        assert doc.status == DocumentStatus.PENDING.value
        assert doc.merchant_id == test_merchant.id
        assert doc.purpose == DocumentPurpose.PRODUCT_IMAGE.value

    @pytest.mark.asyncio
    async def test_invalid_purpose_rejected(self, service, test_merchant):
        """An unknown purpose should raise 400."""
        from fastapi import HTTPException

        payload = DocumentUploadRequest(
            purpose="bogus_purpose",
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create_presigned_upload(str(test_merchant.id), payload)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_content_type_not_allowed(self, service, test_merchant):
        """A content type not allowed for the purpose should raise 400."""
        from fastapi import HTTPException

        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.exe",
            content_type="application/octet-stream",
            size_bytes=1024,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create_presigned_upload(str(test_merchant.id), payload)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_size_too_large_rejected(self, service, test_merchant):
        """A file exceeding the max size should raise 413."""
        from fastapi import HTTPException

        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="big.png",
            content_type="image/png",
            size_bytes=settings.S3_MAX_UPLOAD_MB * 1024 * 1024 + 1,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create_presigned_upload(str(test_merchant.id), payload)
        assert exc_info.value.status_code == 413


class TestCompleteUpload:
    """Tests for DocumentService.complete_upload."""

    @pytest.mark.asyncio
    async def test_complete_upload_marks_complete(
        self, service, test_merchant, db
    ):
        """After uploading to S3 and calling complete, status should be COMPLETE."""
        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        upload_resp = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1016
        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=upload_resp.key,
            Body=png_data,
            ContentType="image/png",
        )

        complete_req = DocumentCompleteRequest(key=upload_resp.key)
        result = await service.complete_upload(complete_req)

        assert result.status == DocumentStatus.COMPLETE.value
        assert result.object_key == upload_resp.key

    @pytest.mark.asyncio
    async def test_complete_upload_not_found(self, service):
        """Completing with a non-existent key should raise 404."""
        from fastapi import HTTPException

        req = DocumentCompleteRequest(key="does/not/exist")
        with pytest.raises(HTTPException) as exc_info:
            await service.complete_upload(req)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_upload_magic_bytes_mismatch(self, service, test_merchant):
        """If the uploaded file's magic bytes don't match the content type, 422."""
        from fastapi import HTTPException

        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        upload_resp = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        fake_data = b"NOT A PNG FILE" + b"\x00" * 990
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=upload_resp.key,
            Body=fake_data,
            ContentType="image/png",
        )

        req = DocumentCompleteRequest(key=upload_resp.key)
        with pytest.raises(HTTPException) as exc_info:
            await service.complete_upload(req)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_complete_upload_idempotent(
        self, service, test_merchant, db
    ):
        """Calling complete on an already-complete document returns it as-is."""
        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        upload_resp = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1016
        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=upload_resp.key,
            Body=png_data,
            ContentType="image/png",
        )

        req = DocumentCompleteRequest(key=upload_resp.key)
        first = await service.complete_upload(req)

        second = await service.complete_upload(req)
        assert second.id == first.id
        assert second.status == DocumentStatus.COMPLETE.value

    @pytest.mark.asyncio
    async def test_complete_upload_links_product(
        self, service, test_merchant, test_product, db
    ):
        """Completing a product_image document appends URL to Product.urls."""
        from app.core.storage import public_url_for

        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
            related_type="Product",
            related_id=str(test_product.id),
        )
        upload_resp = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1016
        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=upload_resp.key,
            Body=png_data,
            ContentType="image/png",
        )

        req = DocumentCompleteRequest(key=upload_resp.key)
        await service.complete_upload(req)

        product = await db.get(Product, test_product.id)
        urls = json.loads(product.urls)
        expected_url = public_url_for(upload_resp.key)
        assert expected_url in urls


class TestListDocuments:
    """Tests for DocumentService.list_documents."""

    @pytest.mark.asyncio
    async def test_list_documents_empty(self, service, test_merchant):
        """An empty result set should return total=0."""
        result = await service.list_documents(
            merchant_id_str=str(test_merchant.id)
        )
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_list_documents_after_upload(self, service, test_merchant):
        """Documents should appear in the list after creation."""
        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        await service.create_presigned_upload(str(test_merchant.id), payload)

        result = await service.list_documents(
            merchant_id_str=str(test_merchant.id)
        )
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].purpose == DocumentPurpose.PRODUCT_IMAGE.value

    @pytest.mark.asyncio
    async def test_list_documents_purpose_filter(self, service, test_merchant):
        """Filtering by purpose should work."""
        payloads = [
            DocumentUploadRequest(
                purpose=DocumentPurpose.PRODUCT_IMAGE.value,
                filename="img.png", content_type="image/png",
                size_bytes=1024,
            ),
            DocumentUploadRequest(
                purpose=DocumentPurpose.KYC.value,
                filename="doc.pdf", content_type="application/pdf",
                size_bytes=1024,
            ),
        ]
        for p in payloads:
            await service.create_presigned_upload(str(test_merchant.id), p)

        result = await service.list_documents(
            merchant_id_str=str(test_merchant.id),
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
        )
        assert result.total == 1
        assert result.items[0].purpose == "product_image"

        result = await service.list_documents(
            merchant_id_str=str(test_merchant.id),
            purpose=DocumentPurpose.KYC.value,
        )
        assert result.total == 1
        assert result.items[0].purpose == "kyc"


class TestGetDocument:
    """Tests for DocumentService.get_document."""

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, service, test_merchant):
        """Get with a random UUID should raise 404."""
        from fastapi import HTTPException

        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_document(str(test_merchant.id), fake_id)
        assert exc_info.value.status_code == 404


class TestDeleteDocument:
    """Tests for DocumentService.delete_document."""

    @pytest.mark.asyncio
    async def test_delete_document_soft_deletes(self, service, test_merchant, db):
        """Delete should mark deleted_at and change status to CLEANUP."""
        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        upload_resp = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=upload_resp.key,
            Body=b"\x89PNG" + b"\x00" * 100,
        )

        result = await service.delete_document(
            str(test_merchant.id), upload_resp.document_id
        )
        assert result is True

        doc = await db.get(Document, uuid.UUID(upload_resp.document_id))
        assert doc is not None
        assert doc.deleted_at is not None
        assert doc.status == DocumentStatus.CLEANUP.value


class TestCleanupStaleDocuments:
    """Tests for DocumentService.cleanup_stale_documents."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_stale_documents(self, service, test_merchant):
        """Stale PENDING documents should be hard-deleted and removed from S3."""
        payload = DocumentUploadRequest(
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            filename="test.png",
            content_type="image/png",
            size_bytes=1024,
        )
        upload_resp = await service.create_presigned_upload(
            str(test_merchant.id), payload
        )

        import boto3

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        s3.put_object(
            Bucket=settings.S3_BUCKET,
            Key=upload_resp.key,
            Body=b"\x89PNG" + b"\x00" * 100,
        )

        doc = await service._db.get(
            Document, uuid.UUID(upload_resp.document_id)
        )
        from datetime import datetime, timezone, timedelta
        doc.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
        await service._db.commit()

        deleted = await service.cleanup_stale_documents(older_than_hours=1)
        assert deleted == 1

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.get_document(
                str(test_merchant.id), upload_resp.document_id
            )
        assert exc_info.value.status_code == 404


class TestPresignedUploadStorage:
    """Tests for the presign_upload storage helper."""

    def test_presign_upload_returns_url_and_fields(self):
        """presign_upload should return a dict with url and fields."""
        key = build_key("test-merchant", "product_image", "test.png")
        result = presign_upload(
            bucket=settings.S3_BUCKET,
            key=key,
            content_type="image/png",
            max_bytes=1024,
            ttl_seconds=60,
        )
        assert "url" in result
        assert "fields" in result
        # presigned POST includes acl field (not Content-Type, which is a condition)

    def test_upload_and_inspect(self):
        """End-to-end: upload, inspect, verify metadata."""
        key = build_key("test-merchant", "product_image", "test.png")
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        upload_file_from_bytes(
            bucket=settings.S3_BUCKET,
            key=key,
            data=data,
            content_type="image/png",
        )

        meta = inspect_object(bucket=settings.S3_BUCKET, key=key)
        assert meta is not None
        assert meta["ContentLength"] == 108
        assert meta["ContentType"] == "image/png"

    def test_delete_object(self):
        """Deleting an object should remove it from S3."""
        key = build_key("test-merchant", "product_image", "test.png")
        upload_file_from_bytes(
            bucket=settings.S3_BUCKET, key=key,
            data=b"\x89PNG" + b"\x00" * 10,
        )

        assert inspect_object(bucket=settings.S3_BUCKET, key=key) is not None

        result = delete_object(bucket=settings.S3_BUCKET, key=key)
        assert result is True

        assert inspect_object(bucket=settings.S3_BUCKET, key=key) is None


# ── Server-side product image upload ───────────────────────────────────────


class TestUploadProductImage:
    """Tests for ``DocumentService.upload_product_image``.

    Unlike ``create_presigned_upload`` / ``complete_upload`` (which are
    designed for browser-to-S3 uploads), ``upload_product_image`` performs a
    server-side upload of an already-received file blob.  It still creates a
    ``COMPLETE`` Document record, pushes the bytes to S3 with
    ``ACL: public-read``, and links the public URL to the product.
    """

    @pytest.fixture
    def png_data(self) -> bytes:
        """A minimal valid PNG payload (header + padding)."""
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    # ── Happy path ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_upload_creates_complete_document(
        self, service, test_product, png_data
    ):
        """The returned DocumentResponse should be COMPLETE with correct metadata."""
        result = await service.upload_product_image(
            product_id_str=str(test_product.id),
            file_data=png_data,
            original_filename="photo.png",
            content_type="image/png",
        )

        assert result.status == DocumentStatus.COMPLETE.value
        assert result.purpose == DocumentPurpose.PRODUCT_IMAGE.value
        assert result.public is True
        assert result.related_type == "Product"
        assert str(result.related_id) == str(test_product.id)
        assert result.size_bytes == len(png_data)
        assert result.filename == "photo.png"

    @pytest.mark.asyncio
    async def test_upload_writes_object_to_s3(
        self, service, test_product, png_data
    ):
        """The bytes should actually exist in the (mocked) S3 bucket."""
        result = await service.upload_product_image(
            product_id_str=str(test_product.id),
            file_data=png_data,
            original_filename="photo.png",
            content_type="image/png",
        )

        meta = inspect_object(
            bucket=settings.S3_BUCKET, key=result.object_key
        )
        assert meta is not None
        assert meta["ContentType"] == "image/png"
        assert meta["ContentLength"] == len(png_data)

    @pytest.mark.asyncio
    async def test_upload_links_url_to_product(
        self, service, test_product, db, png_data
    ):
        """The public URL should be appended to ``Product.urls``."""
        result = await service.upload_product_image(
            product_id_str=str(test_product.id),
            file_data=png_data,
            original_filename="photo.png",
            content_type="image/png",
        )

        product = await db.get(Product, test_product.id)
        urls = json.loads(product.urls)
        expected = public_url_for(result.object_key)
        assert expected in urls

    @pytest.mark.asyncio
    async def test_upload_multiple_images_appends_distinct_urls(
        self, service, test_product, db, png_data
    ):
        """Each call should append a distinct URL to the product."""
        for n in range(3):
            await service.upload_product_image(
                product_id_str=str(test_product.id),
                file_data=png_data,
                original_filename=f"photo{n}.png",
                content_type="image/png",
            )

        product = await db.get(Product, test_product.id)
        urls = json.loads(product.urls)
        assert len(urls) == 3
        assert len(set(urls)) == 3  # all unique

    @pytest.mark.asyncio
    async def test_upload_same_file_produces_unique_keys(
        self, service, test_product, db, png_data
    ):
        """Uploading the same file should still produce a unique S3 key (UUID-based)."""
        r1 = await service.upload_product_image(
            product_id_str=str(test_product.id),
            file_data=png_data,
            original_filename="photo.png",
            content_type="image/png",
        )
        r2 = await service.upload_product_image(
            product_id_str=str(test_product.id),
            file_data=png_data,
            original_filename="photo.png",
            content_type="image/png",
        )

        assert r1.object_key != r2.object_key
        product = await db.get(Product, test_product.id)
        urls = json.loads(product.urls)
        assert len(urls) == 2

    # ── Validation ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_upload_rejects_non_image_content_type(
        self, service, test_product
    ):
        """A content type not in the allowed set should raise 400."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.upload_product_image(
                product_id_str=str(test_product.id),
                file_data=b"some data",
                original_filename="file.exe",
                content_type="application/octet-stream",
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_rejects_size_too_large(
        self, service, test_product
    ):
        """A payload exceeding ``S3_MAX_UPLOAD_MB`` should raise 413."""
        from fastapi import HTTPException

        too_big = b"\x89PNG" + b"\x00" * (
            settings.S3_MAX_UPLOAD_MB * 1024 * 1024 + 1
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_product_image(
                product_id_str=str(test_product.id),
                file_data=too_big,
                original_filename="big.png",
                content_type="image/png",
            )
        assert exc_info.value.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_rejects_empty_file(self, service, test_product):
        """An empty payload should raise 400."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.upload_product_image(
                product_id_str=str(test_product.id),
                file_data=b"",
                original_filename="empty.png",
                content_type="image/png",
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_rejects_magic_byte_mismatch(
        self, service, test_product
    ):
        """Data whose header doesn't match the declared content type \u2192 422."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.upload_product_image(
                product_id_str=str(test_product.id),
                file_data=b"NOT A PNG FILE" + b"\x00" * 100,
                original_filename="fake.png",
                content_type="image/png",
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_rejects_nonexistent_product(self, service, png_data):
        """A product that doesn't exist should raise 404."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.upload_product_image(
                product_id_str=str(uuid.uuid4()),
                file_data=png_data,
                original_filename="photo.png",
                content_type="image/png",
            )
        assert exc_info.value.status_code == 404



class TestPublicUrlFor:
    """Tests for ``public_url_for`` URL construction."""

    def test_returns_s3_url_when_no_base_url(self, monkeypatch):
        """When S3_PUBLIC_BASE_URL is empty, return the S3 REST URL."""
        import app.core.storage as storage_mod
        monkeypatch.setattr(storage_mod.settings, "S3_PUBLIC_BASE_URL", "")
        url = storage_mod.public_url_for("product_image/m-1/uuid.png")
        assert url == (
            f"https://{storage_mod.settings.S3_BUCKET}"
            f".s3.{storage_mod.settings.AWS_REGION}.amazonaws.com"
            f"/product_image/m-1/uuid.png"
        )

    def test_returns_base_url_when_configured(self, monkeypatch):
        """When S3_PUBLIC_BASE_URL is set, prepend it."""
        import app.core.storage as storage_mod
        monkeypatch.setattr(
            storage_mod.settings, "S3_PUBLIC_BASE_URL", "https://cdn.example.com"
        )
        url = storage_mod.public_url_for("product_image/m-1/uuid.png")
        assert url == "https://cdn.example.com/product_image/m-1/uuid.png"

    def test_strips_trailing_slash_from_base(self, monkeypatch):
        """A trailing slash on S3_PUBLIC_BASE_URL should be removed."""
        import app.core.storage as storage_mod
        monkeypatch.setattr(
            storage_mod.settings, "S3_PUBLIC_BASE_URL", "https://cdn.example.com/"
        )
        url = storage_mod.public_url_for("some/key.png")
        assert url == "https://cdn.example.com/some/key.png"
