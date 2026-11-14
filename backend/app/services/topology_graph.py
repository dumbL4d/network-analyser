"""Topology graph engine: redundancy-aware algorithms on the device graph.

Everything here is pure: plain data in, plain data out. No database, no
network, no clock, and no recursion: every traversal keeps its own stack or
queue, so a chain of ten thousand devices cannot hit Python's recursion limit.

The graph
---------
* A VERTEX is a device, named by its id.
* An EDGE is undirected. Two kinds exist and are treated alike: the tree edge
  between a device and its ``parent_id``, and the extra links stored in the
  ``device_link`` table (a second uplink, a ring, ...).
* A ROOT is a device with no parent. The monitoring server sees the network
  through its roots, so "can reach a root" is what "is reachable" means.
* Where an algorithm needs ONE starting point it adds a virtual SUPER-ROOT
  joined to every root. It is an implementation detail and is never returned.

The graph is SIMPLE: at most one edge joins two devices, and no device is
joined to itself. The database guarantees it (app/models/device_link.py) and
``build_graph`` drops any duplicate or self-loop it is handed anyway. The
low-link search relies on this.

In the complexity notes V is the number of devices and E the number of edges
(tree edges plus links).

What is in here
---------------
1. ``build_graph``              adjacency lists and roots from devices + links
2. ``reachable_from_roots``     breadth-first search that stops at unhealthy
                                devices
3. ``low_link_search``          iterative Tarjan depth-first search, and
   ``articulation_points_and_bridges``, its classic use
4. ``blast_radius``             for every device, how many others lose every
                                root if it fails; ``single_points_of_failure``
5. ``DisjointSet``              union-find, used by ``cut_off`` (several
                                failures at once) and ``component_count``
6. ``blast_radius_bruteforce``  the slow, obviously correct reference that the
                                tests compare number 4 with
"""

from collections import deque
from collections.abc import Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass


# The one virtual vertex joined to every root. A bare object is equal only to
# itself, so it can never be mistaken for a device id.
SUPER_ROOT = object()


@dataclass(frozen=True)
class TopologyGraph:
    """An undirected simple graph of devices, and which of them are roots.

    ``adjacency[d]`` lists the neighbours of device ``d``. Every device is a
    key, including one with no neighbours, and the lists are symmetric: if
    ``b`` is in ``adjacency[a]`` then ``a`` is in ``adjacency[b]``.
    """

    adjacency: Mapping[str, Sequence[str]]
    roots: Sequence[str]


# --- 1. adjacency builder ------------------------------------------------------


def build_graph(
    parents: Mapping[str, str | None],
    links: Iterable[tuple[str, str]] = (),
) -> TopologyGraph:
    """Build the device graph from the parent tree and the extra links.

    ``parents`` maps every device id to its ``parent_id`` (None for a
    top-level device). ``links`` are the extra undirected links, as pairs of
    device ids in either order.

    A device whose parent is None, or is not a known device, is a root. An
    edge is added once however often it is given. A self-loop, and a link
    that names an unknown device, are ignored. So the result is always a
    simple graph over exactly the devices in ``parents``.

    Neighbours are listed in the order the edges are given (tree edges first),
    which makes every traversal below deterministic.

    Time O(V + E), space O(V + E).
    """
    adjacency: dict[str, list[str]] = {device: [] for device in parents}
    seen: set[tuple[str, str]] = set()

    def join(a: str, b: str) -> None:
        """Add the edge a-b, unless it is a self-loop, names an unknown
        device, or is there already. O(1)."""
        if a == b or a not in adjacency or b not in adjacency:
            return
        edge = (a, b) if a < b else (b, a)
        if edge not in seen:
            seen.add(edge)
            adjacency[a].append(b)
            adjacency[b].append(a)

    roots: list[str] = []
    for device, parent in parents.items():
        if parent is None or parent not in adjacency:
            roots.append(device)
        else:
            join(device, parent)
    for a, b in links:
        join(a, b)
    return TopologyGraph(adjacency, roots)


def _without(graph: TopologyGraph, removed: Collection[str]) -> TopologyGraph:
    """The graph that is left when the devices in ``removed`` are taken out.

    Time O(V + E), space O(V + E).
    """
    removed = frozenset(removed)
    return TopologyGraph(
        {
            device: [neighbour for neighbour in neighbours if neighbour not in removed]
            for device, neighbours in graph.adjacency.items()
            if device not in removed
        },
        [root for root in graph.roots if root not in removed],
    )


# --- 2. reachability -----------------------------------------------------------


def reachable_from_roots(graph: TopologyGraph, unhealthy: Collection[str] = ()) -> set[str]:
    """The devices that can be reached from a root through healthy devices.

    A device is in the result when some path leads from a root to it on which
    every INTERMEDIATE device is healthy (not in ``unhealthy``). The device
    itself may be unhealthy: it is reached, but nothing is reached THROUGH
    it. A root is always reached; an unhealthy root is an intermediate device
    for everything behind it, so nothing is reached through it either.

    Breadth-first search started from all roots at once, which is the same as
    starting from the super-root. Invariants: a device is put in the queue
    once, at the moment it is first reached, and only a healthy device taken
    from the queue passes the search on to its neighbours.

    Time O(V + E), space O(V).
    """
    unhealthy = frozenset(unhealthy)
    reached = set(graph.roots)
    queue = deque(graph.roots)
    while queue:
        device = queue.popleft()
        if device in unhealthy:
            continue  # reached, but the path ends here
        for neighbour in graph.adjacency[device]:
            if neighbour not in reached:
                reached.add(neighbour)
                queue.append(neighbour)
    return reached


# --- 3. Tarjan: low-link search, articulation points, bridges --------------------


@dataclass(frozen=True)
class LowLink:
    """What a depth-first search recorded about every vertex it visited.

    ``order``      the vertices in the order they were discovered;
    ``discovery``  ``discovery[v]`` is the position of ``v`` in ``order``;
    ``parent``     the vertex ``v`` was discovered from, i.e. its parent in
                   the DFS tree, or None if the search started at ``v``;
    ``low``        the LOW-LINK value: the smallest discovery number that can
                   be reached from ``v`` by going down tree edges (any number,
                   also none) and then along at most one other edge.

    For a tree edge from ``p`` down to ``c``, ``low[c]`` says how high the
    part of the tree below that edge can reach without using it:
    ``low[c] >= discovery[p]`` means "no higher than ``p``", and
    ``low[c] > discovery[p]`` means "not even ``p``".
    """

    order: list[Hashable]
    discovery: dict[Hashable, int]
    parent: dict[Hashable, Hashable | None]
    low: dict[Hashable, int]


def low_link_search(
    adjacency: Mapping[Hashable, Sequence[Hashable]],
    starts: Iterable[Hashable],
) -> LowLink:
    """Depth-first search that numbers every vertex and computes its low-link.

    This is the core of Tarjan's algorithm for articulation points and
    bridges, written with an explicit stack instead of recursion. The search
    starts from each vertex of ``starts`` in turn and skips those an earlier
    start already reached, so a disconnected graph is no problem: pass every
    vertex to cover every component.

    The stack holds one frame per vertex on the path from the current start
    to the vertex being explored: ``(vertex, iterator over its neighbours)``.
    Invariants:

    * a vertex gets its discovery number when its frame is pushed, and the
      numbers are handed out in increasing order;
    * the frames on the stack are exactly the ancestors of the top vertex, so
      an already discovered neighbour that is not the parent is joined by a
      non-tree edge, and ``low`` takes that neighbour's discovery number;
    * when a frame is popped its vertex is finished: its ``low`` is final and
      is passed up to its parent, whose frame is now on top.

    The graph must be simple (see the module docstring): the one edge back to
    the parent is recognised by the parent's identity.

    Time O(V + E): every vertex is pushed and popped once, and every
    adjacency list is walked once by its iterator. Space O(V).
    """
    order: list[Hashable] = []
    discovery: dict[Hashable, int] = {}
    parent: dict[Hashable, Hashable | None] = {}
    low: dict[Hashable, int] = {}

    def discover(vertex: Hashable, found_from: Hashable | None) -> tuple:
        """Number a newly found vertex and return its stack frame. O(1)."""
        discovery[vertex] = low[vertex] = len(order)
        order.append(vertex)
        parent[vertex] = found_from
        return vertex, iter(adjacency[vertex])

    for start in starts:
        if start in discovery:
            continue
        stack = [discover(start, None)]
        while stack:
            vertex, neighbours = stack[-1]
            for neighbour in neighbours:  # resumes where this frame left off
                if neighbour not in discovery:
                    stack.append(discover(neighbour, vertex))  # tree edge: go down
                    break
                if neighbour != parent[vertex]:
                    low[vertex] = min(low[vertex], discovery[neighbour])
            else:
                # Every neighbour has been looked at: ``vertex`` is finished.
                stack.pop()
                if stack:
                    above = stack[-1][0]
                    low[above] = min(low[above], low[vertex])
    return LowLink(order, discovery, parent, low)


def articulation_points_and_bridges(
    graph: TopologyGraph,
) -> tuple[set[str], set[tuple[str, str]]]:
    """The devices and the edges whose loss would split the graph.

    An ARTICULATION POINT is a device whose removal leaves more connected
    pieces than there were. A BRIDGE is an edge with the same property; it is
    returned as ``(a, b)`` with ``a < b``. Both are about the shape of the
    graph only. Roots play no part: ``blast_radius`` answers the root-aware
    question.

    One low-link search over every component, then one pass over the DFS tree
    edges, each going from ``up`` down to ``vertex``:

    * ``low[vertex] > discovery[up]``: nothing below the edge reaches ``up``
      or higher except through the edge itself, so it is a bridge;
    * ``low[vertex] >= discovery[up]``: nothing below the edge reaches higher
      than ``up``, so removing ``up`` cuts that part off from whatever is
      above ``up``. Hence ``up`` is an articulation point, unless it is where
      the search started and nothing is above it;
    * a vertex where the search started is an articulation point exactly when
      it has two or more DFS children: their subtrees meet only in it.

    Time O(V + E), space O(V).
    """
    search = low_link_search(graph.adjacency, graph.adjacency)
    points: set[str] = set()
    bridges: set[tuple[str, str]] = set()
    children_of_start: dict[Hashable, int] = {}
    for vertex in search.order:
        up = search.parent[vertex]
        if up is None:
            continue  # the search started here: no tree edge above it
        if search.low[vertex] > search.discovery[up]:
            bridges.add((up, vertex) if up < vertex else (vertex, up))
        if search.parent[up] is None:
            children_of_start[up] = children_of_start.get(up, 0) + 1
        elif search.low[vertex] >= search.discovery[up]:
            points.add(up)
    points.update(start for start, children in children_of_start.items() if children >= 2)
    return points, bridges


# --- 4. blast radius and single points of failure --------------------------------


def blast_radius(graph: TopologyGraph) -> dict[str, int]:
    """For every device: how many OTHER devices lose every root if it fails.

    ``blast_radius(graph)[d]`` counts the devices that can reach a root today
    and could not if ``d`` were removed. A device that cannot reach a root
    even now is never counted, and its own blast radius is 0.

    How: add the super-root, joined to every root, and run ONE low-link
    search from it. Every device that can reach a root is then in a single
    DFS tree with the super-root on top, so no device is where the search
    started and one rule covers them all. Removing ``up`` cuts off the
    subtree of its DFS child ``vertex`` exactly when
    ``low[vertex] >= discovery[up]``: nothing in that subtree has an edge to
    above ``up``. Every other vertex keeps a path to the super-root that
    avoids ``up``. So

        blast radius of ``up`` = sum of the subtree sizes of those children.

    Subtree sizes come from one backwards pass over the discovery order. A
    descendant is always discovered after its ancestors, so by the time a
    vertex is reached its whole subtree has been added to it.

    Time O(V + E), space O(V + E).
    """
    adjacency: dict[Hashable, Sequence[Hashable]] = dict(graph.adjacency)
    for root in graph.roots:
        adjacency[root] = [*graph.adjacency[root], SUPER_ROOT]
    adjacency[SUPER_ROOT] = list(graph.roots)
    search = low_link_search(adjacency, [SUPER_ROOT])

    subtree_size = dict.fromkeys(search.order, 1)
    for vertex in reversed(search.order):
        up = search.parent[vertex]
        if up is not None:
            subtree_size[up] += subtree_size[vertex]

    radius = dict.fromkeys(graph.adjacency, 0)
    for vertex in search.order:
        up = search.parent[vertex]
        if up is None or up is SUPER_ROOT:
            continue  # the super-root itself, or a root hanging directly off it
        if search.low[vertex] >= search.discovery[up]:
            radius[up] += subtree_size[vertex]
    return radius


def single_points_of_failure(graph: TopologyGraph) -> set[str]:
    """The devices whose failure alone cuts at least one other device off
    from every root: exactly those with a blast radius above 0.

    Time O(V + E), space O(V + E).
    """
    return {device for device, radius in blast_radius(graph).items() if radius > 0}


# --- 5. disjoint sets (union-find) -----------------------------------------------


class DisjointSet:
    """Union-find over a fixed collection of items.

    Keeps the items in groups and answers "are these two in the same group?"
    while groups are being merged. Each group is a tree stored as parent
    pointers; its root is the group's representative.

    * Union by size: the smaller tree is hung under the larger one, so a tree
      with n items is never deeper than log2(n).
    * Path compression: ``find`` re-points every item it passes straight at
      the root, so the next ``find`` on that path is a single step.

    Invariants: ``_parent[x] == x`` exactly for a representative, and
    ``_size[r]`` is the number of items in the group of representative ``r``.

    With both tricks, any sequence of m operations on n items takes
    O(m * alpha(n)) time, alpha being the inverse Ackermann function, which is
    at most 4 for any n that fits in a computer. Space O(n).
    """

    def __init__(self, items: Iterable[Hashable]) -> None:
        """Start with every item in a group of its own. O(n)."""
        self._parent: dict[Hashable, Hashable] = {item: item for item in items}
        self._size: dict[Hashable, int] = dict.fromkeys(self._parent, 1)
        # Number of groups: starts with every item on its own.
        self.groups = len(self._parent)

    def find(self, item: Hashable) -> Hashable:
        """The representative of the group ``item`` is in. Amortised O(alpha(n))."""
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:  # path compression, without recursion
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: Hashable, b: Hashable) -> bool:
        """Merge the groups of ``a`` and ``b``. False if they already were one.

        Amortised O(alpha(n)).
        """
        a, b = self.find(a), self.find(b)
        if a == b:
            return False
        if self._size[a] < self._size[b]:
            a, b = b, a
        self._parent[b] = a  # the smaller group goes under the larger one
        self._size[a] += self._size[b]
        self.groups -= 1
        return True

    def connected(self, a: Hashable, b: Hashable) -> bool:
        """Whether ``a`` and ``b`` are in the same group. Amortised O(alpha(n))."""
        return self.find(a) == self.find(b)


def component_count(graph: TopologyGraph) -> int:
    """The number of connected pieces of the graph (roots play no part).

    Every device starts as its own group and every edge merges two groups.

    Time O((V + E) * alpha(V)), space O(V).
    """
    groups = DisjointSet(graph.adjacency)
    for device, neighbours in graph.adjacency.items():
        for neighbour in neighbours:
            groups.union(device, neighbour)
    return groups.groups


def _connected_to_a_root(graph: TopologyGraph, failed: Collection[str] = ()) -> set[str]:
    """The devices outside ``failed`` that still have a path to a root when
    every device in ``failed`` is gone. Union-find, with the super-root
    merged into the group of each surviving root.

    Time O((V + E) * alpha(V)), space O(V).
    """
    failed = frozenset(failed)
    alive = [device for device in graph.adjacency if device not in failed]
    groups = DisjointSet([SUPER_ROOT, *alive])
    for root in graph.roots:
        if root not in failed:
            groups.union(SUPER_ROOT, root)
    for device in alive:
        for neighbour in graph.adjacency[device]:
            if neighbour not in failed:
                groups.union(device, neighbour)
    return {device for device in alive if groups.connected(device, SUPER_ROOT)}


def cut_off(graph: TopologyGraph, failed: Collection[str]) -> set[str]:
    """The devices that lose every root when ALL of ``failed`` fail together.

    The multi-failure version of the blast radius: a device is in the result
    when it is not itself in ``failed``, can reach a root today, and cannot
    once the failed devices are removed. For a single device ``d``,
    ``len(cut_off(graph, [d])) == blast_radius(graph)[d]``, which is how the
    tests check the blast radius a second, independent way.

    Low-link values only describe the loss of ONE vertex, so this question is
    answered by rebuilding connectivity with union-find instead.

    Time O((V + E) * alpha(V)), space O(V).
    """
    return _connected_to_a_root(graph) - frozenset(failed) - _connected_to_a_root(graph, failed)


# --- 6. brute-force reference (tests only) ---------------------------------------


def blast_radius_bruteforce(graph: TopologyGraph) -> dict[str, int]:
    """The blast radius of every device, computed the slow and obvious way.

    For each device: take it out, search again from the roots, and count the
    devices that were reachable before and are not any more. Exists only so
    the tests can compare ``blast_radius`` with something that is clearly
    right; do not call it from the application.

    Time O(V * (V + E)): one O(V + E) search per device. Space O(V + E).
    """
    reachable = reachable_from_roots(graph)
    return {
        device: len(reachable - {device}) - len(reachable_from_roots(_without(graph, [device])))
        for device in graph.adjacency
    }
