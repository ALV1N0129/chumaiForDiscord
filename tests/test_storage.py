from cryptography.fernet import Fernet

from chumai.storage import LinkStore


def test_sega_token_encrypted(tmp_path):
    key = Fernet.generate_key().decode()
    store = LinkStore(tmp_path / "db.sqlite", key)
    store.set_sega_token(1, "secret-clal")
    raw = store._db.execute("SELECT token FROM sega_tokens").fetchone()[0]
    assert "secret-clal" not in raw
    assert store.get_sega_token(1) == "secret-clal"
    assert store.is_public(1)
    assert store.set_public(1, False) and not store.is_public(1)
    assert store.delete_sega_token(1) and store.get_sega_token(1) is None

