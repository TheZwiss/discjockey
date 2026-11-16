"""The test suite opens SQLCipher files with a raw key it derived itself (tests/speed_sqlcipher.py: SQLCipher's own passphrase
derivation costs ~30 ms on every open). This pins that the two forms are the same cipher: a file made through the
stand-in opens with SQLCipher's own passphrase pragma, a file made with the passphrase opens through the stand-in (so the
raw key is what SQLCipher 4 derives: PBKDF2-HMAC-SHA512, 256000 rounds, the file's own salt), and a wrong key still fails."""
import pytest
import sqlcipher3

import speed_sqlcipher

KEY = "402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a81732a1ff43608497"


def make(path):
    con = sqlcipher3.connect(str(path))
    con.execute(f"PRAGMA key = '{KEY}'")
    con.execute("CREATE TABLE t (word TEXT)")
    con.execute("INSERT INTO t VALUES ('keyed')")
    con.commit()
    con.close()


def read(path, connect, key=KEY):
    con = connect(str(path))
    try:
        con.execute(f"PRAGMA key = '{key}'")
        return con.execute("SELECT word FROM t").fetchall()
    finally:
        con.close()


def test_a_file_made_through_the_stand_in_opens_with_sqlciphers_own_passphrase_pragma(tmp_path):
    make(tmp_path / "a.db")
    assert (tmp_path / "a.db").read_bytes()[:16] == speed_sqlcipher.TEST_SALT
    assert read(tmp_path / "a.db", speed_sqlcipher._real_connect) == [("keyed",)]


@pytest.mark.real_sqlcipher_kdf
def test_a_file_made_with_sqlciphers_own_derivation_opens_through_the_stand_in(tmp_path):
    make(tmp_path / "b.db")
    assert (tmp_path / "b.db").read_bytes()[:16] != speed_sqlcipher.TEST_SALT  # a random salt: the real derivation ran
    speed_sqlcipher._fast_key = True
    assert read(tmp_path / "b.db", sqlcipher3.connect) == [("keyed",)]


def test_a_wrong_key_still_fails_and_a_file_without_its_key_does_not_read(tmp_path):
    make(tmp_path / "c.db")
    with pytest.raises(sqlcipher3.DatabaseError):
        read(tmp_path / "c.db", sqlcipher3.connect, key="ab" * 32)
    with pytest.raises(sqlcipher3.DatabaseError):
        sqlcipher3.connect(str(tmp_path / "c.db")).execute("SELECT word FROM t")
