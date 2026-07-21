"""US1/US2 Integration test: real round-trip against a configured S3-compatible store.

Skipped unless STORAGE_S3_ENDPOINT_URL/BUCKET/ACCESS_KEY/SECRET_KEY point at a
real, already-running instance (see tests/conftest.py's real_s3_storage_env) —
this feature does not provision or manage that instance itself.
"""

import uuid

import pytest

from app.core.config import settings
from app.core.storage import get_storage_backend


@pytest.mark.asyncio
async def test_write_read_exists_list_delete_round_trip(real_s3_storage_env):
    key = f"test/{uuid.uuid4()}.txt"
    prefix = key.rsplit("/", 1)[0]
    payload = b"hello object storage"

    async with get_storage_backend() as s3:
        await s3.put_object(Bucket=settings.storage.s3_bucket, Key=key, Body=payload)

        await s3.head_object(Bucket=settings.storage.s3_bucket, Key=key)

        response = await s3.get_object(Bucket=settings.storage.s3_bucket, Key=key)
        async with response["Body"] as stream:
            body = await stream.read()
        assert body == payload

        listing = await s3.list_objects_v2(Bucket=settings.storage.s3_bucket, Prefix=prefix)
        keys = [obj["Key"] for obj in listing.get("Contents", [])]
        assert keys == [key]

        await s3.delete_object(Bucket=settings.storage.s3_bucket, Key=key)

        with pytest.raises(s3.exceptions.ClientError):
            await s3.head_object(Bucket=settings.storage.s3_bucket, Key=key)
