import os

import certifi

from paperbot.app import ensure_tls_certs


def test_ensure_tls_certs_points_at_certifi_when_unset(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    ensure_tls_certs()
    assert os.environ["SSL_CERT_FILE"] == certifi.where()


def test_ensure_tls_certs_respects_operator_override(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/custom/ca-bundle.pem")
    ensure_tls_certs()
    assert os.environ["SSL_CERT_FILE"] == "/custom/ca-bundle.pem"
