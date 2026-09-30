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



def test_plaintext_token_is_migrated_when_key_is_added(tmp_path):
    LinkStore(tmp_path / "db.sqlite").set_sega_token(1, "old-plain")
    store = LinkStore(tmp_path / "db.sqlite", Fernet.generate_key().decode())
    assert store.get_sega_token(1) == "old-plain"
    raw = store._db.execute("SELECT token FROM sega_tokens").fetchone()[0]
    assert raw.startswith("gAAAA") and store.get_sega_token(1) == "old-plain"


def test_playlog_for_everyone_logged_in(tmp_path):
    import sqlite3

    from chumai.storage import PLAYLOG_NEW, PLAYLOG_OFF

    path = tmp_path / "db.sqlite"
    old = sqlite3.connect(path)  # a database from before the auto column
    old.execute("CREATE TABLE playlog_subs (discord_id INTEGER NOT NULL, game TEXT NOT NULL, "
                "channel_id INTEGER NOT NULL, last_key TEXT NOT NULL DEFAULT '', PRIMARY KEY (discord_id, game))")
    old.execute("INSERT INTO playlog_subs VALUES (1, 'maimai', 10, 'k1')")
    old.commit()
    old.close()
    store = LinkStore(path)
    for who in (1, 2, 3):
        store.set_sega_token(who, f"t{who}")
    store.set_playlog(3, "chunithm", 0, PLAYLOG_OFF, auto=True)  # 3 turned CHUNITHM off

    assert store.add_auto_playlogs(99, ("chunithm", "maimai")) == 4
    subs = {(d, g): (c, k) for d, g, c, k in store.playlogs()}
    assert subs[(1, "maimai")] == (10, "k1")  # their own setting stays
    assert subs[(1, "chunithm")] == (99, PLAYLOG_NEW) and subs[(2, "maimai")] == (99, PLAYLOG_NEW)
    assert (3, "chunithm") not in subs and store.is_auto_playlog(2, "maimai")
    assert store.add_auto_playlogs(98, ("chunithm", "maimai")) == 0  # already there; moved
    moved = {(d, g): c for d, g, c, _ in store.playlogs()}
    assert moved[(1, "chunithm")] == 98 and moved[(2, "maimai")] == 98 and moved[(1, "maimai")] == 10

    store.delete_sega_token(2)  # logging out drops the automatic ones
    assert not any(d == 2 for d, *_ in store.playlogs())
    store.delete_auto_playlogs()
    assert [(d, g) for d, g, *_ in store.playlogs()] == [(1, "maimai")]
    store.add_auto_playlogs(99, ("chunithm",))
    assert (3, "chunithm") not in {(d, g) for d, g, *_ in store.playlogs()}  # still off
    store.close()
