"""Extra links between devices: the four rules a link must obey.

1. no self-loop
2. both devices exist
3. not a duplicate of a tree edge (parent and child)
4. not a duplicate pair, in either order

They are checked by ``check_link`` (pure), enforced when a link is stored
(``add_link``), repeated by the database where one row is enough to tell
(rules 1 and 4), and kept true when devices are deleted or moved.
"""

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import engine
from app.models.device_link import DeviceLink
from app.services.device_links import LinkError, add_link, canonical_pair, check_link

#   core ── s1 ── d
#      └─── s2
PARENTS = {"core": None, "s1": "core", "s2": "core", "d": "s1"}

pytest_db = pytest.mark.usefixtures("db")


def stored_links() -> list[tuple[str, str]]:
    with Session(engine) as session:
        return sorted(
            (link.device_a_id, link.device_b_id) for link in session.exec(select(DeviceLink)).all()
        )


def link(a: str, b: str) -> DeviceLink:
    with Session(engine) as session:
        return add_link(session, a, b)


# --- the rules, pure -----------------------------------------------------------


def test_the_stored_form_of_a_pair_has_the_smaller_id_first():
    assert canonical_pair("s2", "d") == canonical_pair("d", "s2") == ("d", "s2")


def test_a_valid_link_is_returned_in_its_stored_form():
    assert check_link(PARENTS, set(), "s2", "d") == ("d", "s2")
    assert check_link(PARENTS, set(), "d", "s2") == ("d", "s2")
    assert check_link(PARENTS, {("d", "s2")}, "s1", "s2") == ("s1", "s2")  # another pair is fine


@pytest.mark.parametrize(
    ("a", "b", "existing", "message"),
    [
        ("d", "d", set(), "A device cannot be linked to itself"),
        ("d", "ghost", set(), "Device 'ghost' does not exist"),
        ("ghost", "d", set(), "Device 'ghost' does not exist"),
        ("d", "s1", set(), "'d' and 's1' are already connected as parent and child"),
        ("s1", "d", set(), "'s1' and 'd' are already connected as parent and child"),
        ("d", "s2", {("d", "s2")}, "'d' and 's2' are already linked"),
        ("s2", "d", {("d", "s2")}, "'s2' and 'd' are already linked"),  # the other way round
    ],
)
def test_a_link_that_breaks_a_rule_is_rejected(a, b, existing, message):
    with pytest.raises(LinkError) as error:
        check_link(PARENTS, existing, a, b)

    assert str(error.value) == message


# --- storing a link ------------------------------------------------------------


@pytest_db
def test_add_link_stores_the_pair_once_with_the_smaller_id_first():
    stored = link("sw-server", "plc-conveyor-1")

    assert (stored.id is not None, stored.device_a_id, stored.device_b_id) == (
        True,
        "plc-conveyor-1",
        "sw-server",
    )
    assert stored_links() == [("plc-conveyor-1", "sw-server")]


@pytest_db
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("plc-conveyor-1", "sw-server"),  # the same link again
        ("sw-server", "plc-conveyor-1"),  # and written the other way round
        ("scanner-1", "scanner-1"),  # self-loop
        ("scanner-1", "no-such-device"),
        ("scanner-1", "sw-ot"),  # already its parent
        ("sw-edge", "sw-server"),  # already its child
    ],
)
def test_add_link_refuses_a_link_that_breaks_a_rule(a, b):
    link("plc-conveyor-1", "sw-server")

    with pytest.raises(LinkError):
        link(a, b)

    assert stored_links() == [("plc-conveyor-1", "sw-server")]  # nothing was added


@pytest_db
@pytest.mark.parametrize(
    "rows",
    [
        [("scanner-1", "scanner-1")],  # self-loop
        [("sw-server", "plc-conveyor-1")],  # ids in the wrong order: the second way to write a pair
        [("plc-conveyor-1", "sw-server"), ("plc-conveyor-1", "sw-server")],  # duplicate pair
    ],
)
def test_the_database_itself_refuses_what_one_row_can_show(rows):
    """Rules 1 and 4 hold even for code that bypasses ``add_link``."""
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            for device_a_id, device_b_id in rows:
                connection.execute(
                    insert(DeviceLink.__table__).values(device_a_id=device_a_id, device_b_id=device_b_id)
                )

    assert stored_links() == []  # the whole transaction was rolled back


# --- the rules stay true when devices change -------------------------------------


@pytest_db
def test_deleting_a_device_deletes_its_links(client, admin_headers):
    link("scanner-1", "sw-server")  # stored with the scanner first ...
    link("scanner-1", "hmi-panel-1")  # ... and with the scanner second
    link("hmi-panel-1", "sw-server")
    assert stored_links() == [
        ("hmi-panel-1", "scanner-1"),
        ("hmi-panel-1", "sw-server"),
        ("scanner-1", "sw-server"),
    ]

    response = client.delete("/api/devices/scanner-1", headers=admin_headers)

    assert response.status_code == 204
    assert stored_links() == [("hmi-panel-1", "sw-server")]  # both devices of every link exist


@pytest_db
def test_moving_a_device_under_its_link_partner_turns_the_link_into_the_tree_edge(client, admin_headers):
    link("plc-conveyor-1", "sw-server")
    link("hmi-panel-1", "sw-server")

    response = client.patch(
        "/api/devices/plc-conveyor-1", headers=admin_headers, json={"parent_id": "sw-server"}
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] == "sw-server"
    assert stored_links() == [("hmi-panel-1", "sw-server")]  # no link duplicates a tree edge


@pytest_db
def test_a_rejected_move_leaves_the_links_alone(client, admin_headers):
    link("sw-edge", "scanner-1")

    # scanner-1 is below sw-edge, so this would close a loop in the tree.
    response = client.patch("/api/devices/sw-edge", headers=admin_headers, json={"parent_id": "scanner-1"})

    assert response.status_code == 422
    assert stored_links() == [("scanner-1", "sw-edge")]


@pytest_db
def test_an_update_that_does_not_move_the_device_leaves_the_links_alone(client, admin_headers):
    link("plc-conveyor-1", "sw-server")

    response = client.patch("/api/devices/plc-conveyor-1", headers=admin_headers, json={"name": "PLC A"})

    assert response.status_code == 200
    assert stored_links() == [("plc-conveyor-1", "sw-server")]
