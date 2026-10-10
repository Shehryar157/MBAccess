"""Run the swing watcher over a recording: what would the cue have played, and when?

    python tools/replay_swings.py battle2
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import battle, modfiles, walls
from analyse_battle import is_player, load

NATIVE = r"D:\steam\steamapps\common\MountBlade Warband\Modules\Native"


class Frame:
    """Stands in for the game's memory: battle.agents() is replaced by one saved frame."""


def main():
    names = modfiles.load_actions(NATIVE)
    watch = battle.SwingWatch(names)
    frames = load(sys.argv[1])
    real = battle.agents
    count = {"melee": 0, "ranged": 0}
    try:
        for t, frame in frames:
            me = next((d for d in frame.values() if is_player(d)), None)
            if me is None or len(frame) < 3:
                continue
            x, y, z = struct.unpack_from("<3f", me, walls.AGENT_POS)
            facing = struct.unpack_from("<f", me, walls.AGENT_DIRF)[0]
            battle.agents = lambda reader, mission, size, frame=frame: (
                (no, 0, data) for no, data in frame.items())
            # Only frames with everyone in them keep "last action" honest; near ones are in all.
            for kind, distance, angle in watch.check(None, None, (x, y, z, facing, False), t):
                count[kind] += 1
                if count[kind] <= 12:
                    print(f"{t:6.1f} s: {kind}, {distance:.1f} m, {angle:+.0f} degrees")
            mine = struct.unpack_from("<i", me, battle.AGENT_ACTION)[0]
            if mine != getattr(main, "mine", None) and 0 <= mine < len(names):
                main.mine = mine
                if main.shown < 14:
                    main.shown += 1
                    print(f"{t:6.1f} s: YOU {names[mine]}")
            elif mine == -1:
                main.mine = -1
    finally:
        battle.agents = real
    print("cues that would have played:", count)


main.shown = 0
if __name__ == "__main__":
    main()
