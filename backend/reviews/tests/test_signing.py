"""Ed25519 seal signature (I6): offline verification and tamper detection."""

import base64

import pytest

from reviews.services import signing


@pytest.fixture(autouse=True)
def _isolated_key(settings, tmp_path):
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


def payload() -> dict:
    return {
        'v': 1,
        'seal_id': 'abc',
        'version_sha256': 'f' * 64,
        'sections': [{'stable_key': 'objeto', 'body_hash': 'a' * 64}],
        'signed_at': '2026-07-12T10:00:00Z',
    }


@pytest.mark.escenario('D4-F01')
def test_sign_then_verify_roundtrip():
    data = payload()

    signature = signing.sign(data)

    assert signing.verify(data, signature) is True


@pytest.mark.escenario('D4-E03')
def test_tampered_payload_fails_verification():
    data = payload()
    signature = signing.sign(data)

    data['version_sha256'] = '0' * 64

    assert signing.verify(data, signature) is False


def test_tampered_signature_fails_verification():
    data = payload()
    signature = signing.sign(data)
    corrupted = base64.b64encode(b'\x00' * 64).decode()

    assert signing.verify(data, corrupted) is False
    assert signing.verify(data, signature[:-4] + 'AAAA') is False


def test_verification_needs_only_the_public_key():
    """E4 groundwork: a third party verifies with payload+signature+public key."""
    data = payload()
    signature = signing.sign(data)
    public = signing.public_key_b64()

    assert signing.verify(data, signature, public) is True


def test_canonical_bytes_are_order_insensitive():
    a = {'x': 1, 'y': [1, 2]}
    b = {'y': [1, 2], 'x': 1}

    assert signing.canonical_bytes(a) == signing.canonical_bytes(b)


def test_key_id_is_stable_and_short():
    assert signing.key_id() == signing.key_id()
    assert len(signing.key_id()) == 16


def test_key_is_created_once_and_reused(settings, tmp_path):
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'k.pem')

    first = signing.public_key_b64()
    second = signing.public_key_b64()

    assert first == second
    assert (tmp_path / 'k.pem').stat().st_mode & 0o777 == 0o600
