"""Fernet encryption of credential values (research R8)."""

import pytest
from cryptography.fernet import Fernet

from alpaca_gatherer.domain.errors import CredentialsUndecryptable
from alpaca_gatherer.infrastructure.security.fernet_cipher import FernetCipher

PLAIN = "PKTESTKEY1234567890"


def test_round_trip() -> None:
    cipher = FernetCipher(Fernet.generate_key().decode())
    token = cipher.encrypt(PLAIN)
    assert cipher.decrypt(token) == PLAIN


def test_ciphertext_does_not_contain_plain_text() -> None:
    token = FernetCipher(Fernet.generate_key().decode()).encrypt(PLAIN)
    assert PLAIN not in token
    assert token != PLAIN


def test_wrong_key_raises_domain_error_without_secret() -> None:
    token = FernetCipher(Fernet.generate_key().decode()).encrypt(PLAIN)
    with pytest.raises(CredentialsUndecryptable) as info:
        FernetCipher(Fernet.generate_key().decode()).decrypt(token)
    assert PLAIN not in str(info.value)


def test_garbage_token_raises_domain_error() -> None:
    with pytest.raises(CredentialsUndecryptable):
        FernetCipher(Fernet.generate_key().decode()).decrypt("not-a-token")
