"""Object storage key-validation tests."""

import pytest

from app.core.storage import validate_storage_key


def test_accepts_normal_key():
    validate_storage_key("chat/attachments/abc123.pdf")


@pytest.mark.parametrize(
    "key",
    [
        "/etc/passwd",
        "../secrets.txt",
        "chat/../../etc/passwd",
        "chat/../../../secrets.txt",
    ],
)
def test_rejects_path_traversal(key):
    with pytest.raises(ValueError, match="invalid storage key"):
        validate_storage_key(key)
