from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class EncryptedBlob:
    ciphertext: bytes


class FieldEncryptor:
    """Prototype field/blob encryption using a caller-supplied Fernet key."""

    def __init__(self, key: bytes | str) -> None:
        if isinstance(key, str):
            key = key.encode("ascii")
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid Fernet encryption key") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")

    def encrypt(self, plaintext: bytes | str) -> EncryptedBlob:
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        return EncryptedBlob(self._fernet.encrypt(data))

    def decrypt(self, blob: EncryptedBlob | bytes) -> bytes:
        ciphertext = blob.ciphertext if isinstance(blob, EncryptedBlob) else blob
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise ValueError("Encrypted payload could not be authenticated") from exc


def encode_key_for_environment(key: str) -> str:
    """Validate/normalize a key before it is placed in an environment secret."""
    raw = key.encode("ascii")
    Fernet(raw)
    return base64.urlsafe_b64encode(raw).decode("ascii")
