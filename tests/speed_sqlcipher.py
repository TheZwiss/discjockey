"""Test-only: SQLCipher's key stretching is paid once per key and salt, not on every open (installed by conftest.py)."""
import functools
import hashlib
import re
from urllib.parse import unquote, urlparse

import pytest
import sqlcipher3

# The key stretching is paid once per key and salt, not on every open.
#
# SQLCipher turns the passphrase the code sends (`PRAGMA key = '<64 hex>'`, as rekordbox's key is used) into the file key
# with PBKDF2-HMAC-SHA512 over the file's salt (the first 16 bytes), 256000 rounds: about 30 ms on every open of every
# test library, with ~100 opens in a convert or undo test. The tests send the very same pragma; this stand-in for
# `sqlcipher3.connect` only does that derivation itself (hashlib, same parameters) once per passphrase and salt, and
# hands SQLCipher the result as a raw key (`x'<key><salt>'`), which it uses as is. Same cipher, same file format: a
# database made here opens with the plain passphrase pragma and the other way round (pinned by
# tests/test_sqlcipher_key.py). A new file takes `TEST_SALT` as its salt. Tests of the passphrase handling itself
# take `real_sqlcipher_kdf`.

TEST_SALT = bytes(range(16))
_KEY_PRAGMA = re.compile(r"\s*PRAGMA\s+key\s*=\s*'([^']*)'\s*", re.IGNORECASE)
_real_connect = sqlcipher3.connect
_fast_key = True


@functools.lru_cache(maxsize=None)
def raw_key(passphrase: str, salt: bytes) -> str:
    """What SQLCipher 4 (defaults) derives from `passphrase` and the file's `salt`, in its raw-key pragma form."""
    return "x'" + hashlib.pbkdf2_hmac("sha512", passphrase.encode(), salt, 256000, 32).hex() + salt.hex() + "'"


def _salt_of(database) -> bytes:
    path = urlparse(str(database))
    name = unquote(path.path) if path.scheme == "file" else str(database)
    try:
        with open(name, "rb") as f:
            head = f.read(16)
    except OSError:
        return TEST_SALT
    return head if len(head) == 16 else TEST_SALT


class _Connection(sqlcipher3.dbapi2.Connection):
    def __init__(self, database, *a, **k):
        super().__init__(database, *a, **k)
        self._database = database

    def execute(self, sql, *a, **k):
        keyed = _KEY_PRAGMA.fullmatch(sql) if _fast_key and isinstance(sql, str) else None
        if keyed:
            sql = f"PRAGMA key = \"{raw_key(keyed.group(1), _salt_of(self._database))}\""
        return super().execute(sql, *a, **k)


def _connect(database, *a, **k):
    if _fast_key:
        k.setdefault("factory", _Connection)
    return _real_connect(database, *a, **k)


sqlcipher3.connect = _connect




@pytest.fixture(autouse=True)
def _fast_sqlcipher_key(request):
    global _fast_key
    _fast_key = request.node.get_closest_marker("real_sqlcipher_kdf") is None
    yield
    _fast_key = True
