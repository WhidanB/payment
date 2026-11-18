"""Invalid and boundary inputs on the HTTP API."""

from __future__ import annotations

import copy

import pytest

VALID = {
    "idempotency_key": "val-1",
    "amount": 1250,
    "currency": "EUR",
    "reference": {"type": "BOOKING", "id": "resa_1"},
    "source_service": "booking",
}


def body(**overrides):
    data = copy.deepcopy(VALID)
    for dotted, value in overrides.items():
        target = data
        *parents, leaf = dotted.split("__")
        for p in parents:
            target = target[p]
        if value is _MISSING:
            del target[leaf]
        else:
            target[leaf] = value
    return data


_MISSING = object()

INVALID_BODIES = {
    "amount zero": body(amount=0),
    "amount negative": body(amount=-5),
    "amount float": body(amount=12.5),
    "amount string": body(amount="1250"),
    "amount bool": body(amount=True),
    "amount null": body(amount=None),
    "amount above cap": body(amount=10_000_001),
    "amount missing": body(amount=_MISSING),
    "currency usd": body(currency="USD"),
    "currency lowercase": body(currency="eur"),
    "key empty": body(idempotency_key=""),
    "key blank": body(idempotency_key="   "),
    "key too long": body(idempotency_key="k" * 201),
    "key missing": body(idempotency_key=_MISSING),
    "reference id empty": body(reference__id=""),
    "reference id blank": body(reference__id="  "),
    "reference id too long": body(reference__id="r" * 101),
    "reference type unknown": body(reference__type="PIZZA"),
    "reference missing": body(reference=_MISSING),
    "source unknown": body(source_service="parking"),
    "source missing": body(source_service=_MISSING),
}


@pytest.mark.parametrize("payload", INVALID_BODIES.values(), ids=INVALID_BODIES.keys())
def test_invalid_bodies_are_rejected_with_422(client, payload):
    r = client.post("/payments", json=payload)
    assert r.status_code == 422
    assert r.json()["detail"]
    assert client.get("/payments").json() == []  # nothing was created


@pytest.mark.parametrize(
    "kwargs",
    [
        {"content": "not json", "headers": {"content-type": "application/json"}},
        {"content": "[]", "headers": {"content-type": "application/json"}},
        {"content": "null", "headers": {"content-type": "application/json"}},
        {"content": "", "headers": {"content-type": "application/json"}},
        {"data": {"idempotency_key": "form"}},
    ],
    ids=["malformed json", "json array", "json null", "empty body", "form encoded"],
)
def test_malformed_requests_are_rejected_with_422(client, kwargs):
    assert client.post("/payments", **kwargs).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        body(amount=1),
        body(amount=10_000_000),
        body(idempotency_key="k" * 200),
        body(reference__id="r" * 100),
        body(idempotency_key="réservation-é-✓"),
        body(reference__type="PARKING_EXIT", source_service="access"),
    ],
    ids=["1 cent", "max amount", "max key", "max reference id", "unicode key", "access exit"],
)
def test_boundary_values_are_accepted(client, payload):
    assert client.post("/payments", json=payload).status_code == 202


def test_unknown_extra_fields_are_ignored(client):
    r = client.post("/payments", json={**VALID, "note": "free text", "metadata": {"a": 1}})
    assert r.status_code == 202
    assert "note" not in r.json()


def test_whitespace_around_key_is_normalised_so_replay_matches(client):
    first = client.post("/payments", json=body(idempotency_key="  trim-me  "))
    replay = client.post("/payments", json=body(idempotency_key="trim-me"))
    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["payment_id"] == first.json()["payment_id"]
    assert first.json()["idempotency_key"] == "trim-me"


def test_validation_error_names_the_offending_field(client):
    detail = client.post("/payments", json=body(amount=0)).json()["detail"]
    assert detail[0]["loc"][-1] == "amount"


@pytest.mark.parametrize("path", ["/payments/does-not-exist", "/payments/%20", "/payments/" + "x" * 500])
def test_unknown_payment_ids_are_404(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("limit,expected", [(1, 200), (200, 200), (0, 422), (201, 422), ("abc", 422), (-1, 422)])
def test_list_limit_bounds(client, limit, expected):
    assert client.get("/payments", params={"limit": limit}).status_code == expected


def test_wrong_methods_are_405(client):
    assert client.put("/payments", json=VALID).status_code == 405
    assert client.delete("/payments/abc").status_code == 405
    assert client.post("/health").status_code == 405


# -- idempotency conflicts ------------------------------------------------------------


@pytest.mark.parametrize(
    "different",
    [
        body(amount=1251),
        body(reference__id="other"),
        body(reference__type="PARKING_EXIT"),
        body(source_service="access"),
    ],
    ids=["amount", "reference id", "reference type", "source service"],
)
def test_same_key_with_a_different_payload_is_a_409_and_changes_nothing(client, different):
    original = client.post("/payments", json=VALID)
    assert original.status_code == 202

    conflict = client.post("/payments", json=different)

    assert conflict.status_code == 409
    assert "different request" in conflict.json()["detail"]
    stored = client.get(f"/payments/{original.json()['payment_id']}").json()
    assert stored["amount"] == VALID["amount"]
    assert len(stored["transactions"]) == 1
    assert len(client.get("/payments").json()) == 1


def test_same_key_same_payload_stays_a_200_replay(client):
    first = client.post("/payments", json=VALID)
    replay = client.post("/payments", json=VALID)
    assert replay.status_code == 200
    assert replay.json()["payment_id"] == first.json()["payment_id"]
