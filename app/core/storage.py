"""
S3-compatible object storage access (aioboto3).

All blob I/O goes through the client this module hands out so the target
endpoint stays configurable: point STORAGE_S3_ENDPOINT_URL at SeaweedFS (or
any other S3-compatible provider) with zero call-site changes.
"""

import posixpath

import aioboto3
from botocore.config import Config

from app.core.config import settings

_session = aioboto3.Session()


def get_storage_backend():
    """Return a fresh, unentered aioboto3 S3 client for the configured bucket.

    Use as: `async with get_storage_backend() as s3: await s3.put_object(...)`.
    A new client is opened per use (aioboto3's own recommended idiom) rather
    than held open for the process lifetime — cheap, and avoids any
    event-loop-lifecycle coupling since the client is always entered on
    whichever loop is calling it. Not registered as a FastAPI dependency —
    callable from routers, background jobs, and agent/graph nodes alike.
    """
    return _session.client(
        "s3",
        endpoint_url=settings.storage_s3_endpoint_url or None,
        region_name=settings.storage_s3_region,
        aws_access_key_id=settings.storage_s3_access_key,
        aws_secret_access_key=settings.storage_s3_secret_key,
        config=Config(
            s3={"addressing_style": "path" if settings.storage_s3_use_path_style else "virtual"},
            retries={"mode": "standard", "max_attempts": 5},
            connect_timeout=5,
            read_timeout=30,
        ),
    )


def validate_storage_key(key: str) -> None:
    """Reject absolute paths or `..` traversal in a caller-supplied key.

    Call before using any user-influenced key (e.g. built from a filename)
    as an S3 Key. Features should still slugify/UUID-suffix user-supplied
    filename components rather than relying on this check alone.
    """
    if not key or key == ".":
        raise ValueError(f"invalid storage key: {key!r}")
    normalized = posixpath.normpath(key)
    if normalized != key or normalized.startswith("..") or normalized.startswith("/"):
        raise ValueError(f"invalid storage key: {key!r}")
