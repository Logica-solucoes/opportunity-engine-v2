from api import passwords
from api.passwords import hash_password, temp_password, verify_password


def test_hash_roundtrip(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    stored = hash_password("uma senha qualquer")

    assert stored.startswith("scrypt$16384$8$1$")
    assert verify_password("uma senha qualquer", stored)
    assert not verify_password("outra senha", stored)


def test_same_password_gets_different_salt(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    assert hash_password("x" * 12) != hash_password("x" * 12)


def test_tampered_or_garbage_hash_is_rejected(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    stored = hash_password("segredo-123456")
    algo, n, r, p, salt, digest = stored.split("$")
    flipped = ("A" if digest[0] != "A" else "B") + digest[1:]

    assert not verify_password("segredo-123456", "$".join([algo, n, r, p, salt, flipped]))
    assert not verify_password("segredo-123456", "pbkdf2$1$2$3$x$y")
    assert not verify_password("segredo-123456", "lixo")
    assert not verify_password("segredo-123456", "")


def test_params_are_read_from_the_hash(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    old = hash_password("senha-antiga-123")
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**15)

    assert verify_password("senha-antiga-123", old)
    assert hash_password("senha-nova-1234").startswith("scrypt$32768$")


def test_temp_password_is_long_and_random():
    a, b = temp_password(), temp_password()
    assert len(a) >= 12 and a != b
