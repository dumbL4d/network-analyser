"""The topology graph engine (app/services/topology_graph.py).

Three kinds of evidence:

* hand-built graphs small enough to check by eye;
* thousands of seeded random graphs on which the fast algorithms must agree
  with slow, obvious ones (a failing case prints its seed);
* the promise that nothing recurses: a very deep graph still works.

Pure functions throughout, so no database is involved.
"""

import random
import sys
from collections import deque

from app.services.topology_graph import (
    DisjointSet,
    TopologyGraph,
    articulation_points_and_bridges,
    blast_radius,
    blast_radius_bruteforce,
    build_graph,
    component_count,
    cut_off,
    low_link_search,
    reachable_from_roots,
    single_points_of_failure,
)

# =============================================================================
# 1. The adjacency builder
# =============================================================================


def test_build_graph_joins_tree_edges_and_links():
    graph = build_graph({"core": None, "s1": "core", "s2": "core", "d": "s1"}, [("s2", "d")])

    assert graph.roots == ["core"]
    assert graph.adjacency == {
        "core": ["s1", "s2"],
        "s1": ["core", "d"],
        "s2": ["core", "d"],  # the link, seen from s2 ...
        "d": ["s1", "s2"],  # ... and from d
    }


def test_build_graph_keeps_the_graph_simple():
    graph = build_graph(
        {"a": None, "b": "a", "c": "a"},
        [
            ("b", "c"),
            ("c", "b"),  # the same link written the other way round
            ("b", "c"),  # and a plain duplicate
            ("a", "b"),  # duplicates a tree edge
            ("c", "c"),  # self-loop
            ("c", "ghost"),  # unknown device
            ("ghost", "a"),
        ],
    )

    assert graph.adjacency == {"a": ["b", "c"], "b": ["a", "c"], "c": ["a", "b"]}


def test_a_device_without_a_known_parent_is_a_root():
    graph = build_graph({"a": None, "b": "missing", "c": "b", "lonely": None})

    assert graph.roots == ["a", "b", "lonely"]
    assert graph.adjacency == {"a": [], "b": ["c"], "c": ["b"], "lonely": []}


def test_an_empty_topology_is_an_empty_graph():
    graph = build_graph({})

    assert (dict(graph.adjacency), graph.roots) == ({}, [])
    assert reachable_from_roots(graph) == set()
    assert articulation_points_and_bridges(graph) == (set(), set())
    assert blast_radius(graph) == {}
    assert component_count(graph) == 0


# =============================================================================
# Hand-built graphs
# =============================================================================


def chain(*devices: str) -> dict[str, str | None]:
    """Parents for a chain: the first device is the root, each next one hangs
    under the one before it."""
    return {device: (devices[index - 1] if index else None) for index, device in enumerate(devices)}


def test_path():
    # a - b - c - d, with a as the root
    graph = build_graph(chain("a", "b", "c", "d"))

    assert articulation_points_and_bridges(graph) == (
        {"b", "c"},  # the two inner devices
        {("a", "b"), ("b", "c"), ("c", "d")},  # every edge of a tree is a bridge
    )
    assert blast_radius(graph) == {"a": 3, "b": 2, "c": 1, "d": 0}
    assert single_points_of_failure(graph) == {"a", "b", "c"}

    # A tree has no way around any edge, so nothing reaches above itself.
    search = low_link_search(graph.adjacency, graph.adjacency)
    assert search.order == ["a", "b", "c", "d"]
    assert search.low == search.discovery == {"a": 0, "b": 1, "c": 2, "d": 3}
    assert search.parent == {"a": None, "b": "a", "c": "b", "d": "c"}


def test_star():
    leaves = ["l1", "l2", "l3", "l4"]
    hub_is_root = build_graph({"hub": None, **dict.fromkeys(leaves, "hub")})

    assert articulation_points_and_bridges(hub_is_root) == (
        {"hub"},
        {("hub", leaf) for leaf in leaves},
    )
    assert blast_radius(hub_is_root) == {"hub": 4, "l1": 0, "l2": 0, "l3": 0, "l4": 0}

    # The same shape entered through a leaf: the root is a SPOF although it is
    # no articulation point (removing a leaf never splits a graph).
    leaf_is_root = build_graph({"l1": None, "hub": "l1", "l2": "hub", "l3": "hub", "l4": "hub"})

    assert articulation_points_and_bridges(leaf_is_root)[0] == {"hub"}
    assert blast_radius(leaf_is_root) == {"l1": 4, "hub": 3, "l2": 0, "l3": 0, "l4": 0}
    assert single_points_of_failure(leaf_is_root) == {"l1", "hub"}


def test_cycle():
    # a - b - c - d - a, with a as the root: every device has two ways round.
    graph = build_graph(chain("a", "b", "c", "d"), [("d", "a")])

    assert articulation_points_and_bridges(graph) == (set(), set())
    assert blast_radius(graph) == {"a": 3, "b": 0, "c": 0, "d": 0}  # only the root matters
    assert single_points_of_failure(graph) == {"a"}

    # Everything on the ring can climb back to the first vertex.
    search = low_link_search(graph.adjacency, graph.adjacency)
    assert search.low == {"a": 0, "b": 0, "c": 0, "d": 0}


def test_two_cycles_sharing_a_node():
    #   r - a          c
    #    \  |        /   \     ring r-a-s and ring s-c-d meet in s only
    #       s ------      d
    #       |_____________|
    graph = build_graph(
        {"r": None, "a": "r", "s": "a", "c": "s", "d": "c"},
        [("s", "r"), ("d", "s")],
    )

    assert articulation_points_and_bridges(graph) == ({"s"}, set())  # no bridge: all edges are on a ring
    assert blast_radius(graph) == {"r": 4, "a": 0, "s": 2, "c": 0, "d": 0}
    assert single_points_of_failure(graph) == {"r", "s"}

    search = low_link_search(graph.adjacency, graph.adjacency)
    assert search.discovery == {"r": 0, "a": 1, "s": 2, "c": 3, "d": 4}
    # c and d can climb to s (number 2) but no higher: that is what makes s an
    # articulation point. The first ring climbs all the way to r.
    assert search.low == {"r": 0, "a": 0, "s": 0, "c": 2, "d": 2}


def disconnected_graph() -> TopologyGraph:
    # Three pieces and a loner. Only the first two pieces contain a root.
    return TopologyGraph(
        {
            "r1": ["x"],
            "x": ["r1"],
            "r2": ["y"],
            "y": ["r2", "z"],
            "z": ["y"],
            "i": ["j"],  # an island that no root can reach
            "j": ["i"],
            "loner": [],
        },
        ["r1", "r2"],
    )


def test_disconnected_graph():
    graph = disconnected_graph()

    assert component_count(graph) == 4
    assert reachable_from_roots(graph) == {"r1", "x", "r2", "y", "z"}
    assert articulation_points_and_bridges(graph) == (
        {"y"},
        {("r1", "x"), ("r2", "y"), ("y", "z"), ("i", "j")},  # found in every piece
    )
    # The island and the loner cannot reach a root to begin with: they are
    # never counted, and losing one of them costs nobody anything.
    assert blast_radius(graph) == {
        "r1": 1, "x": 0, "r2": 2, "y": 1, "z": 0, "i": 0, "j": 0, "loner": 0,
    }  # fmt: skip
    assert blast_radius_bruteforce(graph) == blast_radius(graph)
    assert single_points_of_failure(graph) == {"r1", "r2", "y"}


def test_multiple_roots():
    # r1 - m - r2, and a leaf hanging off m
    graph = build_graph({"r1": None, "r2": None, "m": "r1", "leaf": "m"}, [("m", "r2")])

    assert graph.roots == ["r1", "r2"]
    assert articulation_points_and_bridges(graph)[0] == {"m"}
    # Losing a root costs nothing while the other root is still there.
    assert blast_radius(graph) == {"r1": 0, "r2": 0, "m": 1, "leaf": 0}
    assert single_points_of_failure(graph) == {"m"}


def test_an_articulation_point_between_two_roots_is_not_a_single_point_of_failure():
    # r1 - relay - r2: removing the relay splits the graph in two, but each
    # half still contains a root, so nobody is cut off.
    graph = build_graph({"r1": None, "r2": None, "relay": "r1"}, [("relay", "r2")])

    assert articulation_points_and_bridges(graph)[0] == {"relay"}
    assert blast_radius(graph) == {"r1": 0, "r2": 0, "relay": 0}
    assert single_points_of_failure(graph) == set()


DUAL_HOMED = {"core": None, "s1": "core", "s2": "core", "d": "s1"}


def test_dual_homed_device():
    # d has two uplinks: s1 (its parent) and s2 (an extra link).
    graph = build_graph(DUAL_HOMED, [("d", "s2")])

    assert articulation_points_and_bridges(graph) == (set(), set())
    assert blast_radius(graph) == {"core": 3, "s1": 0, "s2": 0, "d": 0}
    assert single_points_of_failure(graph) == {"core"}

    # Take the second uplink away and s1 becomes a single point of failure.
    single_homed = build_graph(DUAL_HOMED)

    assert articulation_points_and_bridges(single_homed) == (
        {"core", "s1"},
        {("core", "s1"), ("core", "s2"), ("d", "s1")},
    )
    assert blast_radius(single_homed) == {"core": 3, "s1": 1, "s2": 0, "d": 0}
    assert single_points_of_failure(single_homed) == {"core", "s1"}


# =============================================================================
# 2. Reachability through healthy devices
# =============================================================================


def test_everything_joined_to_a_root_is_reachable_when_all_are_healthy():
    assert reachable_from_roots(build_graph(chain("a", "b", "c", "d"))) == {"a", "b", "c", "d"}


def test_an_unhealthy_device_is_reached_but_nothing_is_reached_through_it():
    graph = build_graph(chain("a", "b", "c", "d"))

    assert reachable_from_roots(graph, {"b"}) == {"a", "b"}
    assert reachable_from_roots(graph, {"d"}) == {"a", "b", "c", "d"}  # the last one blocks nothing


def test_an_unhealthy_root_is_reached_and_blocks_what_is_behind_it():
    assert reachable_from_roots(build_graph(chain("a", "b", "c")), {"a"}) == {"a"}


def test_a_second_uplink_keeps_a_device_reachable():
    graph = build_graph(DUAL_HOMED, [("d", "s2")])

    assert reachable_from_roots(graph, {"s1"}) == {"core", "s1", "s2", "d"}  # round the other way
    assert reachable_from_roots(graph, {"s1", "s2"}) == {"core", "s1", "s2"}  # both uplinks gone
    assert reachable_from_roots(build_graph(DUAL_HOMED), {"s1"}) == {"core", "s1", "s2"}  # no link


def test_nothing_is_reachable_without_a_root():
    graph = TopologyGraph({"a": ["b"], "b": ["a"]}, [])

    assert reachable_from_roots(graph) == set()


# =============================================================================
# 5. Union-find, and several failures at once
# =============================================================================


def test_disjoint_set_merges_groups_and_counts_them():
    groups = DisjointSet("abcde")
    assert groups.groups == 5
    assert not groups.connected("a", "b")

    assert groups.union("a", "b") is True
    assert groups.union("c", "d") is True
    assert groups.union("b", "a") is False  # already one group: nothing changes
    assert groups.groups == 3

    assert groups.union("a", "d") is True
    assert groups.connected("b", "c")
    assert not groups.connected("b", "e")
    assert groups.groups == 2
    assert len({groups.find(item) for item in "abcd"}) == 1


def test_union_hangs_the_smaller_group_under_the_larger_one():
    groups = DisjointSet("abcd")
    groups.union("a", "b")
    groups.union("a", "c")
    big = groups.find("a")

    groups.union("d", "a")  # the single item is named first, and still goes underneath

    assert groups.find("d") == big


def test_find_compresses_the_path_it_walked():
    groups = DisjointSet("abcd")
    groups._parent.update({"a": "b", "b": "c", "c": "d"})  # a chain a -> b -> c -> d

    assert groups.find("a") == "d"
    assert groups._parent == {"a": "d", "b": "d", "c": "d", "d": "d"}  # all point at the top now


def test_cut_off_handles_several_failures_at_once():
    graph = build_graph(DUAL_HOMED, [("d", "s2")])

    assert cut_off(graph, ["s1"]) == set()  # one uplink left
    assert cut_off(graph, ["s2"]) == set()
    assert cut_off(graph, ["s1", "s2"]) == {"d"}  # neither failure alone does this
    assert cut_off(graph, ["core"]) == {"s1", "s2", "d"}
    assert cut_off(graph, []) == set()
    assert cut_off(graph, ["s1", "s2", "d"]) == set()  # a failed device is not "cut off"


def test_cut_off_never_counts_a_device_that_had_no_root_anyway():
    assert cut_off(disconnected_graph(), ["r2", "i"]) == {"y", "z"}


# =============================================================================
# Property tests: seeded random graphs against slow, obvious code
# =============================================================================

TREE_CASES = 600
GRAPH_CASES = 1500


def random_tree(rng: random.Random, max_devices: int = 14) -> dict[str, str | None]:
    """Parents of a random tree: every device hangs under an earlier one."""
    count = rng.randint(1, max_devices)
    parents: dict[str, str | None] = {"d00": None}
    for index in range(1, count):
        parents[f"d{index:02d}"] = f"d{rng.randrange(index):02d}"
    return parents


def random_graph(rng: random.Random, max_devices: int = 12) -> TopologyGraph:
    """Any simple graph: sparse or dense, connected or in pieces, with any
    number of roots (also none), loners, and pieces that contain no root."""
    if rng.random() < 0.3:
        # Built the way the application does it: a forest plus links, some of
        # them junk that the builder has to drop.
        count = rng.randint(1, max_devices)
        devices = [f"d{index:02d}" for index in range(count)]
        parents = {
            device: None if index == 0 or rng.random() < 0.2 else devices[rng.randrange(index)]
            for index, device in enumerate(devices)
        }
        links = [(rng.choice(devices), rng.choice(devices)) for _ in range(rng.randint(0, count))]
        return build_graph(parents, links)

    count = rng.randint(1, max_devices)
    devices = [f"d{index:02d}" for index in range(count)]
    rng.shuffle(devices)  # so that ids are not in discovery order
    density = rng.choice([0.0, 0.08, 0.15, 0.25, 0.4, 0.7])
    adjacency: dict[str, list[str]] = {device: [] for device in devices}
    for index, a in enumerate(devices):
        for b in devices[index + 1 :]:
            if rng.random() < density:
                adjacency[a].append(b)
                adjacency[b].append(a)
    for neighbours in adjacency.values():
        rng.shuffle(neighbours)
    root_share = rng.choice([0.0, 0.1, 0.2, 0.5])
    return TopologyGraph(adjacency, [device for device in devices if rng.random() < root_share])


def reach(graph: TopologyGraph, removed: set[str] = frozenset()) -> set[str]:
    """Plain breadth-first search from the roots with some devices taken out."""
    seen = {root for root in graph.roots if root not in removed}
    queue = deque(seen)
    while queue:
        for neighbour in graph.adjacency[queue.popleft()]:
            if neighbour not in removed and neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def pieces(graph: TopologyGraph, removed: set[str] = frozenset(), cut: tuple[str, str] | None = None) -> int:
    """Number of connected pieces, by repeated breadth-first search, with
    some devices and optionally one edge taken out."""
    seen: set[str] = set()
    count = 0
    for start in graph.adjacency:
        if start in removed or start in seen:
            continue
        count += 1
        seen.add(start)
        queue = deque([start])
        while queue:
            device = queue.popleft()
            for neighbour in graph.adjacency[device]:
                if neighbour in removed or neighbour in seen or cut in ((device, neighbour), (neighbour, device)):
                    continue
                seen.add(neighbour)
                queue.append(neighbour)
    return count


def edges(graph: TopologyGraph) -> set[tuple[str, str]]:
    return {(a, b) for a, neighbours in graph.adjacency.items() for b in neighbours if a < b}


def test_blast_radius_matches_brute_force_on_random_trees():
    for seed in range(TREE_CASES):
        parents = random_tree(random.Random(seed))
        graph = build_graph(parents)

        radius = blast_radius(graph)

        assert radius == blast_radius_bruteforce(graph), f"seed {seed}: {parents}"
        # In a tree with one root, a device takes exactly its descendants with it.
        descendants = dict.fromkeys(parents, 0)
        for device in reversed(list(parents)):  # children are listed after their parent
            if parents[device] is not None:
                descendants[parents[device]] += descendants[device] + 1
        assert radius == descendants, f"seed {seed}: {parents}"
        assert single_points_of_failure(graph) == {d for d, n in descendants.items() if n}, f"seed {seed}"


def test_blast_radius_and_spofs_match_brute_force_on_random_graphs():
    for seed in range(GRAPH_CASES):
        graph = random_graph(random.Random(seed))
        context = f"seed {seed}: {graph}"

        radius = blast_radius(graph)
        brute = blast_radius_bruteforce(graph)

        assert radius == brute, context
        assert single_points_of_failure(graph) == {d for d, n in brute.items() if n > 0}, context
        # A second, independent check: union-find instead of searching.
        assert radius == {device: len(cut_off(graph, [device])) for device in graph.adjacency}, context
        # And the brute force itself against the definition, spelled out.
        before = reach(graph)
        assert brute == {
            device: len(before - {device} - reach(graph, {device})) for device in graph.adjacency
        }, context


def test_articulation_points_and_bridges_match_their_definitions_on_random_graphs():
    for seed in range(GRAPH_CASES):
        graph = random_graph(random.Random(seed))
        context = f"seed {seed}: {graph}"
        whole = pieces(graph)

        points, bridges = articulation_points_and_bridges(graph)

        # Removing the device (or the edge) leaves more pieces than before.
        assert points == {d for d in graph.adjacency if pieces(graph, {d}) > whole}, context
        assert bridges == {edge for edge in edges(graph) if pieces(graph, cut=edge) > whole}, context


def test_low_link_values_satisfy_their_definition_on_random_graphs():
    for seed in range(GRAPH_CASES):
        graph = random_graph(random.Random(seed))
        context = f"seed {seed}: {graph}"

        search = low_link_search(graph.adjacency, graph.adjacency)

        # Every device is numbered exactly once, in the order it was found.
        assert sorted(search.discovery.values()) == list(range(len(graph.adjacency))), context
        assert [search.discovery[device] for device in search.order] == list(range(len(search.order))), context
        for device, up in search.parent.items():
            if up is not None:  # a tree edge goes to a neighbour found earlier
                assert up in graph.adjacency[device], context
                assert search.discovery[up] < search.discovery[device], context
        # low = the smallest number reachable by tree edges down, then at most
        # one other edge. Recomputed here bottom-up from the finished DFS tree.
        expected: dict[str, int] = {}
        for device in reversed(search.order):
            candidates = [search.discovery[device]]
            for neighbour in graph.adjacency[device]:
                if search.parent[neighbour] == device:
                    candidates.append(expected[neighbour])  # a child: tree edge down
                elif neighbour != search.parent[device]:
                    candidates.append(search.discovery[neighbour])  # any other edge
            expected[device] = min(candidates)
        assert search.low == expected, context


def test_union_find_counts_components_like_breadth_first_search():
    for seed in range(GRAPH_CASES):
        graph = random_graph(random.Random(seed))
        context = f"seed {seed}: {graph}"

        assert component_count(graph) == pieces(graph), context

        # The same for single questions: are these two devices in one piece?
        groups = DisjointSet(graph.adjacency)
        for a, b in edges(graph):
            groups.union(a, b)
        assert groups.groups == pieces(graph), context
        label: dict[str, str] = {}
        for start in graph.adjacency:  # label every piece by breadth-first search
            if start not in label:
                label[start] = start
                queue = deque([start])
                while queue:
                    for neighbour in graph.adjacency[queue.popleft()]:
                        if neighbour not in label:
                            label[neighbour] = start
                            queue.append(neighbour)
        for a in graph.adjacency:
            for b in graph.adjacency:
                assert groups.connected(a, b) == (label[a] == label[b]), context


def test_cut_off_matches_breadth_first_search_for_random_sets_of_failures():
    for seed in range(GRAPH_CASES):
        rng = random.Random(seed)
        graph = random_graph(rng)
        devices = list(graph.adjacency)
        failed = set(rng.sample(devices, rng.randint(0, len(devices))))

        assert cut_off(graph, failed) == reach(graph) - failed - reach(graph, failed), (
            f"seed {seed}: {graph} failed={sorted(failed)}"
        )


def test_reachability_matches_its_definition_on_random_graphs():
    for seed in range(GRAPH_CASES):
        rng = random.Random(seed)
        graph = random_graph(rng)
        unhealthy = {device for device in graph.adjacency if rng.random() < 0.35}

        # The definition in two steps: first the healthy devices that are
        # joined to a healthy root through healthy devices only ...
        healthy_part = TopologyGraph(graph.adjacency, [root for root in graph.roots if root not in unhealthy])
        through = reach(healthy_part, unhealthy)
        # ... then the roots themselves, and every neighbour of those devices.
        expected = set(graph.roots) | through | {n for device in through for n in graph.adjacency[device]}

        assert reachable_from_roots(graph, unhealthy) == expected, (
            f"seed {seed}: {graph} unhealthy={sorted(unhealthy)}"
        )


# =============================================================================
# No recursion
# =============================================================================


def test_a_very_deep_graph_does_not_hit_the_recursion_limit():
    depth = 20_000  # a recursive depth-first search would fail at about 1,000
    assert depth > 10 * sys.getrecursionlimit()
    devices = [f"d{index:05d}" for index in range(depth)]
    graph = build_graph(chain(*devices))

    radius = blast_radius(graph)
    points, bridges = articulation_points_and_bridges(graph)

    assert (radius[devices[0]], radius[devices[1]], radius[devices[-1]]) == (depth - 1, depth - 2, 0)
    assert len(points) == depth - 2  # all but the two ends
    assert len(bridges) == depth - 1
    assert len(reachable_from_roots(graph)) == depth
    assert component_count(graph) == 1

    # Union-find's ``find`` walks a long chain without recursing as well.
    groups = DisjointSet(devices)
    groups._parent.update(zip(devices, devices[1:]))  # d00000 -> d00001 -> ... -> the last
    assert groups.find(devices[0]) == devices[-1]
