"""Study a recording from tools/record_battle.py.

    python tools/analyse_battle.py arena1 timeline        who was there over time, the player's health
    python tools/analyse_battle.py arena1 teams 150       small-number fields at second 150 (team guesses)
    python tools/analyse_battle.py arena1 player 140 160  the player's fields that changed in that window
"""
import gzip
import os
import pickle
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import walls
from record_battle import HEALTH, LOGS, PARTS, at

TROOP = 0x298


def offsets():
    for a, b in PARTS:
        yield from range(a, b, 4)


def load(name):
    with gzip.open(os.path.join(LOGS, name + ".pkl.gz"), "rb") as f:
        return pickle.load(f)["frames"]


def i32(data, offset):
    return struct.unpack_from("<i", data, at(data, offset))[0]


def f32(data, offset):
    return struct.unpack_from("<f", data, at(data, offset))[0]


def is_player(data):
    return i32(data, walls.AGENT_TYPE) == 0 and i32(data, walls.AGENT_FLAGS) & 1


def timeline(frames):
    last = None
    for t, frame in frames:
        me = next((d for d in frame.values() if is_player(d)), None)
        if me is None:
            continue
        line = (round(f32(me, HEALTH)), i32(me, walls.AGENT_STATUS))
        if line != last:
            print(f"{t:6.1f} s: your health {line[0]}, status {line[1]}")
            last = line
    full = [(t, len(frame)) for t, frame in frames if len(frame) > 1]
    for (t, n), (_t, before) in zip(full[1:], full):
        if n != before:
            print(f"{t:6.1f} s: {before} -> {n} agents")


def teams(frames, second):
    t, frame = min((f for f in frames if len(f[1]) > 2), key=lambda f: abs(f[0] - second))
    people = {no: d for no, d in frame.items() if i32(d, walls.AGENT_TYPE) == 0}
    print(f"at {t:.1f} s: {len(people)} people; order:",
          [("YOU" if is_player(d) else no, i32(d, TROOP), round(f32(d, HEALTH))) for no, d in people.items()])
    for offset in offsets():
        values = [i32(d, offset) for d in people.values()]
        if all(-1 <= v <= 15 for v in values) and len(set(values)) > 1:
            print(f"  +{offset:#x}: {values}")


def player(frames, start, end):
    seen = [(t, d) for t, frame in frames for d in frame.values() if is_player(d) and start <= t <= end]
    print(f"{len(seen)} player frames; health", [round(f32(d, HEALTH)) for _t, d in seen][::5])
    for offset in offsets():
        values = [i32(d, offset) for _t, d in seen]
        distinct = sorted(set(values))
        if 1 < len(distinct) <= 8 and all(-2 <= v <= 400 for v in distinct):
            runs = [values[0]]
            for v in values[1:]:
                if v != runs[-1]:
                    runs.append(v)
            if len(runs) <= 60:
                print(f"  +{offset:#x}: values {distinct}, sequence {runs[:40]}")


if __name__ == "__main__":
    frames = load(sys.argv[1])
    what = sys.argv[2]
    if what == "timeline":
        timeline(frames)
    elif what == "teams":
        teams(frames, float(sys.argv[3]))
    else:
        player(frames, float(sys.argv[3]), float(sys.argv[4]))
