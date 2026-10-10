"""Passive recorder: snapshots of every fighter while the user plays a fight.

    python tools/record_battle.py [seconds] [name]     record (default 300 s) to logs/<name>.pkl.gz
    python tools/record_battle.py read [name]          summary of a recording

Reads only: the user plays, we watch. The player's agent is saved five times a second,
everyone else once a second; only the parts of the agent struct where fighting fields
live (PARTS). Creating the file logs/stop ends a recording early.
"""
import gzip
import os
import pickle
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import battle, process, scanner, session, walls
from mbaccess.mem import ReadError, Reader

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
PARTS = ((0, 0x900), (0x5900, 0x6200))      # byte ranges of an agent we keep
HEALTH = 0x6000                             # hit_points_float (found 2026-10-10)


def keep(data):
    return b"".join(data[a:b] for a, b in PARTS)


def at(saved, offset):
    """Where an agent offset sits in a saved (cut-down) agent."""
    start = 0
    for a, b in PARTS:
        if a <= offset < b:
            return start + offset - a
        start += b - a
    raise KeyError(offset)


def record(seconds, name):
    game = process.try_attach()
    found, _ = session.locate(game)
    reader = Reader(game)
    offsets = game.profile.screen["party_skills"]
    troops = reader.u32(found + offsets["troops"])
    frames, names = [], {}
    stop = os.path.join(LOGS, "stop")
    if os.path.exists(stop):
        os.remove(stop)
    start, tick = time.time(), 0
    while time.time() - start < seconds and not os.path.exists(stop):
        time.sleep(0.2)
        tick += 1
        try:
            mission = walls.mission_address(reader, game.profile)
            frame = {}
            for no, _address, data in battle.agents(reader, mission):
                kind, _, _status, flags = struct.unpack_from("<iiiI", data, walls.AGENT_TYPE)
                mine = kind == battle.HUMAN and flags & 1
                if mine or tick % 5 == 0:
                    frame[no] = keep(data)
                    if no not in names:
                        troop = struct.unpack_from("<i", data, scanner.AGENT_TROOP)[0]
                        names[no] = ("YOU " if mine else "") + ("horse" if kind == battle.HORSE else
                                     reader.rgl_string(troops + troop * offsets["troop_size"] + 4))
            frames.append((time.time() - start, frame))
        except (ReadError, OSError, struct.error):
            continue
    path = os.path.join(LOGS, name + ".pkl.gz")
    with gzip.open(path, "wb") as f:
        pickle.dump({"frames": frames, "names": names}, f)
    print(f"{len(frames)} frames, {len(names)} fighters, saved to {path}")


def read(name):
    with gzip.open(os.path.join(LOGS, name + ".pkl.gz"), "rb") as f:
        saved = pickle.load(f)
    frames, names = saved["frames"], saved["names"]
    print(f"{len(frames)} frames over {frames[-1][0]:.0f} s, {len(names)} fighters")
    for no, name_ in sorted(names.items()):
        seen = [(t, frame[no]) for t, frame in frames if no in frame]
        health = [struct.unpack_from("<f", data, at(data, HEALTH))[0] for _t, data in seen]
        status = [struct.unpack_from("<i", data, walls.AGENT_STATUS)[0] for _t, data in seen]
        print(f"  {no:3} {name_}: seen {seen[0][0]:.0f}-{seen[-1][0]:.0f} s, health {health[0]:.0f} -> "
              f"{health[-1]:.0f} (lowest {min(health):.0f}), status {status[0]} -> {status[-1]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "read":
        read(sys.argv[2] if len(sys.argv) > 2 else "battle")
    else:
        record(float(sys.argv[1]) if len(sys.argv) > 1 else 300,
               sys.argv[2] if len(sys.argv) > 2 else "battle")
