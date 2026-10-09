"""Walls around the player in a 3D scene (town, village, castle, battle).

Read the scene's collision shapes once per scene, slice them at chest height into
2D lines and circles, and cast rays around the player to find the nearest wall in
each direction. Pure maths on numbers read from memory: no engine calls.

Memory layout (Warband 1.174, found 2026-10-09, see docs/findings/scenes.md):
- [cur_game_ptr - 4] -> mission (points at its scene field); [mission] -> scene.
- mission+4: agents (rgl::stable_vector): chunks of 16 agents, list begin at +0x20.
- scene+0x58: stored_bodies vector (begin, end): every collision shape.
"""
import math
import struct

import numpy as np

from .mem import ReadError

# Shape kinds by vtable (1.174). Found by decoding each kind's fields.
QUAD, COMPOSITE, CAPSULE, SPHERE = 0x7c131c, 0x7c1474, 0x7c12bc, 0x7c1264
# body_part flags (WSE rgl_body_part.h)
BF_NO_COLLISION, BF_TERRAIN_QUAD = 0x2, 0x10

AGENT_SIZE = 0x6200
AGENT_POS, AGENT_DIRF, AGENT_TYPE, AGENT_STATUS, AGENT_FLAGS = 0x40, 0x20, 0x28, 0x30, 0x34

# Slice heights above the agent's feet: knee and chest. One height flickered when a
# fence top or a wall's lower edge sat near it on sloping ground (ride test 2026-10-10).
HEIGHTS = (0.5, 1.3)
# The stored angle (+0x20) is a quarter turn behind the way the agent walks forward
# (ride test 2026-10-10: forward always moved at stored + 90 degrees).
FORWARD = math.pi / 2


def mission_address(reader, profile):
    """The mission pointer sits just before cur_game in the engine's globals."""
    return reader.u32(profile.game_offsets["cur_game_ptr"] - 4)


def find_player(reader, mission):
    """(x, y, z, facing radians, on_horse) for the player's agent, or None."""
    begin, end = struct.unpack("<II", reader.read(mission + 0x20, 8))
    if not begin or end <= begin or end - begin > 4 * 1000:
        return None
    chunks = struct.unpack("<%dI" % ((end - begin) // 4), reader.read(begin, end - begin))
    player = None
    horses = []
    for chunk in chunks:
        for i in range(16):
            a = chunk + i * AGENT_SIZE
            try:
                h = reader.read(a, 0x50)
            except ReadError:
                continue
            valid = struct.unpack_from("<i", h, 4)[0]
            kind, _, status, flags = struct.unpack_from("<iiiI", h, AGENT_TYPE)
            if valid != 1 or status != 1:
                continue
            x, y, z = struct.unpack_from("<3f", h, AGENT_POS)
            facing = struct.unpack_from("<f", h, AGENT_DIRF)[0]
            if kind == 1:
                horses.append((x, y))
            elif flags & 1:
                player = (x, y, z, facing)
    if player is None:
        return None
    x, y = player[0], player[1]
    on_horse = any(abs(hx - x) < 0.05 and abs(hy - y) < 0.05 for hx, hy in horses)
    return player + (on_horse,)


class SceneWalls:
    """The scene's obstacles, read once. slice() and cast() do the per-tick work."""

    def __init__(self, reader, scene):
        self.scene = scene
        quads, capsules, spheres = [], [], []
        with reader.cached():
            begin, end = struct.unpack("<II", reader.read(scene + 0x58, 8))
            items = struct.unpack("<%dI" % ((end - begin) // 4), reader.read(begin, end - begin))
            stack = list(items)
            while stack:        # walk the shape tree: composites hold more shapes
                p = stack.pop()
                try:
                    h = reader.read(p, 0x120)
                except ReadError:
                    continue
                vtable, _, flags = struct.unpack_from("<IiI", h, 0)
                if flags & (BF_NO_COLLISION | BF_TERRAIN_QUAD):
                    continue
                if vtable == COMPOSITE:
                    parts, n = struct.unpack_from("<Ii", h, 0x44)
                    if 0 < n < 100000:
                        stack.extend(struct.unpack("<%dI" % n, reader.read(parts, 4 * n)))
                elif vtable == QUAD:
                    nz = struct.unpack_from("<f", h, 0xc4 + 8)[0]
                    if abs(nz) < 0.7:           # upright: a wall, not a floor or roof
                        quads.append([struct.unpack_from("<3f", h, 0x44 + 16 * k) for k in range(4)])
                elif vtable == CAPSULE:
                    a = struct.unpack_from("<3f", h, 0x44)
                    b = struct.unpack_from("<3f", h, 0x54)
                    radius = struct.unpack_from("<f", h, 0x84)[0]
                    if 0 < radius < 20:
                        capsules.append(a + b + (radius,))
                elif vtable == SPHERE:
                    c = struct.unpack_from("<3f", h, 0x54)
                    radius = struct.unpack_from("<f", h, 0x64)[0]
                    if 0 < radius < 20:
                        spheres.append(c + (radius,))
        self.quads = np.array(quads, dtype=np.float64).reshape(-1, 4, 3)
        self.capsules = np.array(capsules, dtype=np.float64).reshape(-1, 7)
        self.spheres = np.array(spheres, dtype=np.float64).reshape(-1, 4)
        self._slices = {}           # height (25 cm steps) -> (segments, circles)

    def counts(self):
        return len(self.quads), len(self.capsules), len(self.spheres)

    def slice(self, height):
        """2D segments (M,2,2) and circles (K,3: x, y, r) where the walls cross `height`."""
        key = round(height * 4) / 4         # redo only when height changes by 25 cm
        if key in self._slices:
            return self._slices[key]
        if len(self._slices) > 64:
            self._slices.clear()
        segments = []
        q = self.quads
        if len(q):
            # each quad edge k runs from corner k to corner k+1
            a, b = q, np.roll(q, -1, axis=1)
            za, zb = a[..., 2] - key, b[..., 2] - key
            crosses = (za * zb) < 0
            t = np.where(crosses, za / np.where(crosses, za - zb, 1), 0)
            pts = a[..., :2] + t[..., None] * (b[..., :2] - a[..., :2])
            for i in np.nonzero(crosses.sum(axis=1) >= 2)[0]:
                hit = pts[i][crosses[i]]
                segments.append((hit[0], hit[1]))
        circles = []
        for x1, y1, z1, x2, y2, z2, r in self.capsules:
            if min(z1, z2) - r > key or max(z1, z2) + r < key:
                continue
            length2d = math.hypot(x2 - x1, y2 - y1)
            steps = max(1, int(length2d / max(r, 0.2)))
            for s in range(steps + 1):  # a lying log becomes a row of circles
                f = s / steps
                circles.append((x1 + f * (x2 - x1), y1 + f * (y2 - y1), r))
        for x, y, z, r in self.spheres:
            dz = abs(z - key)
            if dz < r:
                circles.append((x, y, math.sqrt(r * r - dz * dz)))
        result = (np.array(segments, dtype=np.float64).reshape(-1, 2, 2),
                  np.array(circles, dtype=np.float64).reshape(-1, 3))
        self._slices[key] = result
        return result

    def cast(self, x, y, height, angles, reach=15.0):
        """Distance along each angle (radians, world frame) to the first wall; reach if none."""
        segments, circles = self.slice(height)
        d = np.stack([np.cos(angles), np.sin(angles)], axis=1)       # (R,2) ray directions
        best = np.full(len(angles), reach)
        o = np.array([x, y])
        if len(segments):
            a, e = segments[:, 0], segments[:, 1] - segments[:, 0]
            near = np.minimum(np.abs(a - o).max(axis=1), np.abs(segments[:, 1] - o).max(axis=1)) < reach + 20
            a, e = a[near], e[near]
            ao = a - o                                               # (M,2)
            cross = lambda u, v: u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]
            denom = cross(d[:, None, :], e[None, :, :])              # (R,M)
            safe = np.where(np.abs(denom) < 1e-9, np.nan, denom)
            t = cross(ao[None, :, :], e[None, :, :]) / safe
            s = cross(ao[None, :, :], d[:, None, :]) / safe
            hit = (t >= 0) & (s >= 0) & (s <= 1)
            best = np.minimum(best, np.where(hit, t, reach).min(axis=1, initial=reach))
        if len(circles):
            f = o - circles[:, :2]                                   # (K,2)
            b = d @ f.T                                              # (R,K)
            c = (f * f).sum(axis=1) - circles[:, 2] ** 2
            disc = b * b - c[None, :]
            t = -b - np.sqrt(np.maximum(disc, 0))
            t = np.where(c[None, :] < 0, 0, t)                       # standing inside
            hit = (disc >= 0) & (t >= 0)
            best = np.minimum(best, np.where(hit, t, reach).min(axis=1, initial=reach))
        return best


ZONES = ("front", "right", "behind", "left")


def zone_distances(walls, player, rays=32, reach=15.0):
    """Nearest wall in each quarter around the player: {zone: metres}."""
    x, y, z, stored, _ = player
    rel = np.arange(rays) * (2 * math.pi / rays)       # 0 = straight ahead, clockwise
    angles = stored + FORWARD - rel     # world angles: anticlockwise, so clockwise = minus
    dist = np.minimum.reduce([walls.cast(x, y, z + h, angles, reach) for h in HEIGHTS])
    out = {}
    for i, name in enumerate(ZONES):
        centre = i * math.pi / 2
        diff = np.abs((rel - centre + math.pi) % (2 * math.pi) - math.pi)
        out[name] = float(dist[diff <= math.pi / 4 + 1e-9].min())
    return out
