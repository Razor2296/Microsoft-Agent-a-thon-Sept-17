"""Unit tests for multi-user ACA session isolation."""

from server.session_store import SessionApiStore, normalize_session_id


class _FakeApi:
    def __init__(self, tenant_key: str):
        self._tenant_key = tenant_key
        self.marker = object()


def test_normalize_session_id_mints_when_empty():
    sid = normalize_session_id("")
    assert sid.startswith("sess_")
    assert len(sid) >= 12


def test_normalize_session_id_sanitizes_unsafe_chars():
    sid = normalize_session_id("abc/../evil session!!")
    assert "/" not in sid
    assert " " not in sid
    assert ".." not in sid


def test_session_store_isolates_api_instances():
    created = []

    def factory(sid: str):
        api = _FakeApi(sid)
        created.append(sid)
        return api

    store = SessionApiStore(factory=factory, ttl_seconds=3600, max_sessions=10)
    sid_a, api_a = store.get_or_create("client_alpha_01")
    sid_b, api_b = store.get_or_create("client_bravo_02")

    assert sid_a != sid_b
    assert api_a is not api_b
    assert api_a.marker is not api_b.marker
    assert api_a._tenant_key == sid_a
    assert api_b._tenant_key == sid_b
    assert store.active_count() == 2

    sid_a2, api_a2 = store.get_or_create(sid_a)
    assert sid_a2 == sid_a
    assert api_a2 is api_a
    assert len(created) == 2


def test_session_store_evicts_when_at_capacity():
    def factory(sid: str):
        return _FakeApi(sid)

    store = SessionApiStore(factory=factory, ttl_seconds=3600, max_sessions=2)
    store.get_or_create("session_one_xx")
    store.get_or_create("session_two_yy")
    assert store.active_count() == 2
    store.get_or_create("session_three_zz")
    assert store.active_count() == 2
