"""Passive probe: the fighters in the scene, to find where health and teams are stored.

    python tools/probe_battle.py            everyone: troop, alive, place, health guesses
    python tools/probe_battle.py teams      also the fields that could be a team number
    python tools/probe_battle.py watch      print what changes in the player's agent, twice a second

Reads only. Run it in any scene first (a village), then in a fight (the arena): the
health offset must hold for everyone, and a team field must split the two sides.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import battle, process, scanner, session, walls
from mbaccess.mem import Reader


def main():
    game = process.try_attach()
    found, _ = session.locate(game)
    reader = Reader(game)
    mission = walls.mission_address(reader, game.profile)
    everyone = list(battle.agents(reader, mission))
    alive = [a for a in everyone if struct.unpack_from("<i", a[2], walls.AGENT_STATUS)[0] == battle.ALIVE]
    print(f"{len(everyone)} agents, {len(alive)} alive")
    health = battle.find_health([data for _no, _at, data in alive])
    print("health offsets (spawn, max, now, whole):", [hex(o) for o in health[:8]])
    offsets = game.profile.screen["party_skills"]
    troops = reader.u32(found + offsets["troops"])
    for no, at, data in everyone:
        kind, _, status, flags = struct.unpack_from("<iiiI", data, walls.AGENT_TYPE)
        x, y, z = struct.unpack_from("<3f", data, walls.AGENT_POS)
        troop = struct.unpack_from("<i", data, scanner.AGENT_TROOP)[0]
        name = "horse" if kind == battle.HORSE else reader.rgl_string(troops + troop * offsets["troop_size"] + 4)
        points = ["%.0f/%.0f" % struct.unpack_from("<2f", data, o + 4)[::-1] for o in health[:2]]
        print(f"  {no:3} {'YOU ' if flags & 1 and kind == battle.HUMAN else ''}{name}, status {status}, "
              f"at {x:.1f} {y:.1f} {z:.1f}, health {points}")
    if "teams" in sys.argv:
        people = [data for _no, _at, data in alive
                  if struct.unpack_from("<i", data, walls.AGENT_TYPE)[0] == battle.HUMAN]
        for offset, values in battle.small_int_fields(people).items():
            print(f"  +{offset:#x}: {values}")
    if "watch" in sys.argv:
        me = next(at for _no, at, data in alive
                  if struct.unpack_from("<I", data, walls.AGENT_FLAGS)[0] & 1
                  and struct.unpack_from("<i", data, walls.AGENT_TYPE)[0] == battle.HUMAN)
        before = game.read(me, 0x1000)
        while True:
            time.sleep(0.5)
            now = game.read(me, 0x1000)
            changed = [f"+{o:#x} {struct.unpack_from('<i', before, o)[0]}->{struct.unpack_from('<i', now, o)[0]}"
                       for o in range(0x50, 0x1000, 4) if before[o:o + 4] != now[o:o + 4]]
            if changed:
                print(time.strftime("%H:%M:%S"), ", ".join(changed[:14]))
            before = now


if __name__ == "__main__":
    main()
