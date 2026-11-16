"""Single-use tickets for the status stream: the store, and the two endpoints
that issue and redeem them."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.deps import get_stream_user
from app.db.session import engine
from app.models.user import User
from app.services.stream_tickets import TICKET_SECONDS, TicketStore, stream_tickets
from tests.test_rate_limit import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(0.0)


@pytest.fixture
def store(clock) -> TicketStore:
    return TicketStore(clock=clock)


# =============================================================================
# The store
# =============================================================================


def test_a_ticket_is_redeemed_for_the_user_it_was_issued_to(store):
    ticket = store.issue("viewer")

    assert store.redeem(ticket) == "viewer"


def test_a_ticket_works_only_once(store):
    ticket = store.issue("admin")

    assert store.redeem(ticket) == "admin"
    assert store.redeem(ticket) is None


def test_an_unknown_ticket_is_refused(store):
    store.issue("admin")

    assert store.redeem("not-a-ticket") is None
    assert store.redeem("") is None


def test_a_ticket_expires_after_30_seconds(store, clock):
    assert (TICKET_SECONDS, store.ttl_seconds) == (30.0, 30.0)
    in_time, too_late = store.issue("admin"), store.issue("admin")

    clock.set(29.9)
    assert store.redeem(in_time) == "admin"
    clock.set(30.0)
    assert store.redeem(too_late) is None


def test_tickets_are_long_random_strings(store):
    tickets = {store.issue("admin") for _ in range(50)}

    assert len(tickets) == 50  # no two alike
    assert all(len(ticket) >= 43 for ticket in tickets)  # 32 random bytes, base64


def test_expired_tickets_are_purged_when_a_ticket_is_issued(store, clock):
    for _ in range(3):
        store.issue("admin")
    assert len(store) == 3

    clock.set(30.0)
    fresh = store.issue("admin")

    assert len(store) == 1
    assert store.redeem(fresh) == "admin"


def test_expired_tickets_are_purged_when_a_ticket_is_redeemed(store, clock):
    store.issue("admin")
    store.issue("admin")

    clock.set(31.0)
    assert store.redeem("not-a-ticket") is None

    assert len(store) == 0


def test_a_redeemed_ticket_is_forgotten_at_once_and_stays_forgotten(store, clock):
    used = store.issue("admin")
    kept = store.issue("viewer")
    assert store.redeem(used) == "admin"
    assert len(store) == 1

    clock.set(30.0)  # the purge passes over the used ticket without harm
    assert store.redeem(used) is None
    assert store.redeem(kept) is None
    assert len(store) == 0
    assert len(store._expiries) == 0  # nothing left behind in memory


def test_a_purge_only_drops_the_tickets_that_have_expired(store, clock):
    older = store.issue("admin")
    clock.set(20.0)
    newer = store.issue("viewer")

    clock.set(35.0)  # older is 35 s old, newer 15 s
    assert store.redeem(older) is None
    assert len(store) == 1
    assert store.redeem(newer) == "viewer"


# =============================================================================
# POST /api/stream/ticket and GET /api/stream/status?ticket=
# =============================================================================
#
# A stream that was opened never ends, and the TestClient cannot read such a
# response. So a ticket is redeemed through the stream's own dependency, and
# the stream is only requested where it answers with an error.


def _ticket(client, headers) -> str:
    response = client.post("/api/stream/ticket", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


async def _open_stream(ticket: str | None) -> User:
    with Session(engine) as session:
        return await get_stream_user(ticket=ticket, session=session)


def _stream(client, **params):
    response = client.get("/api/stream/status", params=params)
    return response.status_code, response.json()


REFUSED = (401, {"detail": "Invalid or expired stream ticket"})


@pytest.mark.parametrize("role", ["admin", "viewer"])
def test_any_logged_in_user_gets_a_ticket(client, admin_headers, viewer_headers, role):
    headers = admin_headers if role == "admin" else viewer_headers

    response = client.post("/api/stream/ticket", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ticket", "expires_in"}
    assert body["expires_in"] == 30
    assert len(stream_tickets) == 1


async def test_a_ticket_opens_the_stream_as_the_user_who_asked_for_it(client, viewer_headers):
    user = await _open_stream(_ticket(client, viewer_headers))

    assert (user.username, user.role) == ("viewer", "viewer")


async def test_a_ticket_opens_the_stream_only_once(client, admin_headers):
    ticket = _ticket(client, admin_headers)
    await _open_stream(ticket)

    assert _stream(client, ticket=ticket) == REFUSED
    with pytest.raises(HTTPException) as refused:
        await _open_stream(ticket)
    assert refused.value.status_code == 401


def test_the_stream_refuses_a_ticket_it_did_not_issue(client):
    assert _stream(client, ticket="not-a-ticket") == REFUSED
    assert _stream(client, ticket="") == REFUSED


def test_the_stream_refuses_an_expired_ticket(client, admin_headers):
    clock = FakeClock()
    stream_tickets.__init__(clock=clock)
    ticket = _ticket(client, admin_headers)

    clock.advance(30.0)

    assert _stream(client, ticket=ticket) == REFUSED


def test_the_stream_without_a_ticket_is_401(client):
    response = client.get("/api/stream/status")

    assert (response.status_code, response.json()) == (401, {"detail": "Not authenticated"})
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_login_token_no_longer_opens_the_stream(client, admin_headers):
    token = admin_headers["Authorization"].removeprefix("Bearer ")

    # Neither in the old ?token= parameter, nor passed off as a ticket.
    assert _stream(client, token=token) == (401, {"detail": "Not authenticated"})
    assert _stream(client, ticket=token) == REFUSED


def test_a_ticket_is_good_for_the_stream_and_nothing_else(client, admin_headers):
    ticket = _ticket(client, admin_headers)

    response = client.get("/api/devices", headers={"Authorization": f"Bearer {ticket}"})

    assert response.status_code == 401


def test_a_ticket_of_a_user_who_was_deleted_meanwhile_is_refused(client, admin_headers, viewer_headers):
    ticket = _ticket(client, viewer_headers)
    with Session(engine) as session:
        viewer = session.exec(select(User).where(User.username == "viewer")).one()
    assert client.delete(f"/api/users/{viewer.id}", headers=admin_headers).status_code == 204

    assert _stream(client, ticket=ticket) == REFUSED
