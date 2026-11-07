"""Orders a consistently wound triangle mesh so that collision_write.make_pack joins it into long strips.

make_pack joins a triangle to the strip before it when it holds the strip's last two vertices and winds the other
way (the game's FindFaceInTriStrip alternates InTriR / InTriL, notes "Part 2: writers"). In a mesh whose triangles
all wind the same way, the neighbour across a strip's last edge (v[k+1], v[k+2]) holds that edge reversed, so it winds
the other way as a strip triangle: walking from a triangle across its last edge to an unused neighbour, again and
again, gives triangles in strip order. Fewer strips mean fewer strip spheres for the game's height query to test.
"""


def order(tris):
    """The same triangles in an order that makes strips (a strip's first triangle may be rotated: same winding)."""
    edges = {}
    for n, t in enumerate(tris):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edges.setdefault((a, b) if a < b else (b, a), []).append(n)
    used = [False] * len(tris)
    out = []

    def next_across(a, b):
        for m in edges.get((a, b) if a < b else (b, a), ()):
            if not used[m]:
                return m
        return None

    def free_neighbours(n):
        t = tris[n]
        return sum(1 for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))
                   if any(not used[m] and m != n for m in edges[(a, b) if a < b else (b, a)]))

    # start each strip at a triangle with the fewest free neighbours (the mesh's edge first, as SGI's stripifier),
    # so strips run inwards instead of stranding single triangles
    import heapq
    heap = [(free_neighbours(n), n) for n in range(len(tris))]
    heapq.heapify(heap)
    while heap:
        deg, start = heapq.heappop(heap)
        if used[start]:
            continue
        now = free_neighbours(start)
        if now > deg:
            heapq.heappush(heap, (now, start))
            continue
        t = tris[start]
        # start with the rotation whose last edge leads on to an unused neighbour (if any)
        best = (t[0], t[1], t[2])
        for rot in ((t[0], t[1], t[2]), (t[1], t[2], t[0]), (t[2], t[0], t[1])):
            used[start] = True
            m = next_across(rot[1], rot[2])
            used[start] = False
            if m is not None:
                best = rot
                break
        used[start] = True
        out.append(best)
        a, b = best[1], best[2]
        while True:
            m = next_across(a, b)
            if m is None:
                break
            used[m] = True
            out.append(tris[m])
            c = [p for p in tris[m] if p != a and p != b]
            if len(c) != 1:
                break
            a, b = b, c[0]
    return out
