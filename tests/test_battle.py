import struct

from mbaccess import battle


def agent(health_at, spawn, most, now, team_at=None, team=0, size=0x400):
    data = bytearray(size)
    struct.pack_into("<3fi", data, health_at, spawn, most, now, round(now))
    if team_at is not None:
        struct.pack_into("<i", data, team_at, team)
    return bytes(data)


def test_health_is_found_where_every_agent_has_the_shape():
    group = [agent(0x200, 45, 45, 45), agent(0x200, 60, 60, 12.4), agent(0x200, 38, 38, 0)]
    assert battle.find_health(group) == [0x200]


def test_health_needs_the_whole_number_to_match():
    data = bytearray(agent(0x200, 45, 45, 30))
    struct.pack_into("<i", data, 0x20c, 7)
    assert battle.find_health([bytes(data)]) == []


def test_team_fields_are_small_numbers_that_differ():
    group = [agent(0x200, 45, 45, 45, 0x300, 0), agent(0x200, 45, 45, 45, 0x300, 1)]
    assert battle.small_int_fields(group) == {0x300: [0, 1]}
