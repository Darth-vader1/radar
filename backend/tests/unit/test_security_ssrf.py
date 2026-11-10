import pytest

from app.core.security import SSRFValidationError, validate_outbound_url


def test_reject_invalid_scheme():
    with pytest.raises(SSRFValidationError, match="Invalid URL scheme"):
        validate_outbound_url("ftp://example.com/data.json")

    with pytest.raises(SSRFValidationError, match="Invalid URL scheme"):
        validate_outbound_url("file:///etc/passwd")

    with pytest.raises(SSRFValidationError, match="Invalid URL scheme"):
        validate_outbound_url("gopher://127.0.0.1:70")


def test_reject_credentials_in_url():
    with pytest.raises(SSRFValidationError, match="embedded authentication credentials"):
        validate_outbound_url("https://admin:secret@example.com/api")


def test_reject_cloud_metadata():
    with pytest.raises(SSRFValidationError, match="prohibited address"):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")


def test_reject_loopback():
    with pytest.raises(SSRFValidationError, match="prohibited address"):
        validate_outbound_url("http://127.0.0.1/internal")

    with pytest.raises(SSRFValidationError, match="prohibited address"):
        validate_outbound_url("http://localhost/api")


def test_reject_private_rfc1918():
    with pytest.raises(SSRFValidationError, match="prohibited address"):
        validate_outbound_url("http://10.0.0.5/admin")

    with pytest.raises(SSRFValidationError, match="prohibited address"):
        validate_outbound_url("http://192.168.1.100/status")

    with pytest.raises(SSRFValidationError, match="prohibited address"):
        validate_outbound_url("http://172.16.50.2/api")


def test_reject_prohibited_port():
    with pytest.raises(SSRFValidationError, match="not in allowed outbound ports"):
        validate_outbound_url("http://example.com:22/ssh", allowed_ports=[80, 443])


def test_allow_legitimate_public_url():
    # Valid public URL should pass through safely
    url = "https://example.com"
    validated = validate_outbound_url(url)
    assert validated == url
