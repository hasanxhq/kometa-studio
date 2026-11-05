"""Encryption for secrets Studio keeps in SQLite, such as the plex.tv account token.

The key lives in its own file next to the database, readable only by Studio's
user, so a copy of studio.db on its own (a backup, a bug report) doesn't leak
the secrets in it.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_FILE = "secret.key"


class SecretBox:
    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    @classmethod
    def load_or_create(cls, data_dir: Path) -> "SecretBox":
        path = data_dir / KEY_FILE
        try:
            return cls(path.read_bytes().strip())
        except FileNotFoundError:
            pass
        data_dir.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        try:
            # O_EXCL: if two processes race, the loser reads the winner's key below.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return cls(path.read_bytes().strip())
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return cls(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str | None:
        """Return the plaintext, or None if the key changed since it was encrypted."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            return None
