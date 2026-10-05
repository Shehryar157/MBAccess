"""Party skills, rebuilt from the heroes in the player's party.

The party screen draws its "Party Skills" lines ("Path-finding (2)(+1)")
straight to the screen and never keeps them as text, so we work them out
the way the engine does (docs/findings/screens.md):
- a party skill's level is the best level among the heroes in the party
  (you and your companions; a wounded hero still counts);
- the leader adds a bonus from their own level: +1 at 2 to 4, +2 at 5 to 7,
  +3 at 8 or 9, +4 at 10. Verified only for 1 (no bonus) and 2 (+1).

Memory (profile screen["party_skills"], Warband 1.174):
- game+troops: pointer to the troops array (troop 0 = the player), each
  troop "troop_size" bytes; its flags at "troop_flags" (0x10 = hero) and six
  ints of skill levels at "troop_skills", 4 bits a skill, 8 skills an int.
- game+parties: an stl::vector of party pointers; the player's party has the
  id "p_main_party" at "party_id". Its troop stacks (32 bytes each: count,
  troop number, flags, spawned, wounded...) start at the pointer at
  "stacks", and "num_stacks" says how many are used.
"""
import struct

from .mem import ReadError
from .modfiles import SF_EFFECTS_PARTY

TF_HERO = 0x10
STACK_SIZE = 32
MAIN_PARTY = "p_main_party"


def leader_bonus(level):
    if level < 2:
        return 0
    return 1 if level < 5 else 2 if level < 8 else 3 if level < 10 else 4


def unpack_skills(words, count):
    """Six packed ints -> a list of levels; skill n is the n-th group of 4 bits."""
    return [(words[n // 8] >> 4 * (n % 8)) & 0xF for n in range(count)]


class PartySkills:
    def __init__(self, reader, offsets):
        self.reader = reader
        self.o = offsets
        self.party = {}         # game object -> its main party's address

    def main_party(self, game):
        if game not in self.party:
            r = self.reader
            for at in r.vector(game + self.o["parties"], 4):
                party = r.ptr(at)
                if party and r.rgl_string(party + self.o["party_id"]) == MAIN_PARTY:
                    self.party[game] = party
                    break
            else:
                return None
        return self.party[game]

    def heroes(self, game, count):
        """[(name, skill levels)] of the heroes in the player's party, leader first."""
        r, o = self.reader, self.o
        party = self.main_party(game)
        if party is None:
            return []
        troops = r.ptr(game + o["troops"])
        stacks = r.ptr(party + o["stacks"])
        found = []
        for n in range(min(r.i32(party + o["num_stacks"]), 32)):
            number, troop_no = struct.unpack("<ii", r.read(stacks + n * STACK_SIZE, 8))
            troop = troops + troop_no * o["troop_size"]
            if number < 1 or not r.u32(troop + o["troop_flags"]) & TF_HERO:
                continue
            words = struct.unpack("<6I", r.read(troop + o["troop_skills"], 24))
            found.append((r.rgl_string(troop + 4), unpack_skills(words, count)))
        return found

    def lines(self, game, skills):
        """What the screen shows, e.g. ["Surgery 1", "Path-finding 2 +1"].
        When a companion has the best level, their name follows."""
        try:
            heroes = self.heroes(game, len(skills))
        except ReadError:
            return []
        if not heroes:
            return []
        result = []
        for n, skill in enumerate(skills):
            if not skill.flags & SF_EFFECTS_PARTY:
                continue
            best_name, best = max(((name, levels[n]) for name, levels in heroes),
                                  key=lambda h: h[1])
            if best == 0:
                continue
            line = f"{skill.name} {min(best, skill.max_level)}"
            bonus = leader_bonus(heroes[0][1][n])
            if bonus:
                line += f" +{bonus}"
            if best_name != heroes[0][0] and best > heroes[0][1][n]:
                line += f", {best_name}"
            result.append(line)
        return result
