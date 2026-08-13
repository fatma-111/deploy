"""SSRF protection."""

import pytest

from app.tools.http_client import UnsafeURLError, assert_safe_url, is_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://db.internal/health",
    ],
)
def test_private_and_odd_schemes_are_blocked(url):
    assert is_safe_url(url) is False
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_public_https_is_allowed():
    assert is_safe_url("https://github.com/langchain-ai/langchain") is True
