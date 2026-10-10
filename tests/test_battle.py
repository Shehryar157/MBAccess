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


def test_a_raised_weapon_is_told_by_its_animation_name():
    assert battle.wind_up("ready_slashright_onehanded") == "melee"
    assert battle.wind_up("ready_overswing_musket") == "melee"      # a musket used as a club
    assert battle.wind_up("ready_bow") == "ranged"
    assert battle.wind_up("ready_throwing_knife") == "ranged"
    assert battle.wind_up("release_slashright_onehanded") is None
    assert battle.wind_up("defend_shield_keep") is None


def test_action_names_are_read_in_order():
    from mbaccess import modfiles
    text = "2\n stand 0 16777216  1\n  3.0 anim_human 50 52 0 0 0.0 0.0 0.0 0.25 \n ready_bow 1 2  1\n  1.0 x 1 2 0 0 0.0 0.0 0.0 0.0 \n"
    assert modfiles.parse_actions(text) == ["stand", "ready_bow"]


def test_other_teams_are_enemies_and_bystanders_are_nobody():
    assert battle.side(6, 3) == "Enemies"
    assert battle.side(6, 6) == "Allies"
    assert battle.side(6, -1) is None and battle.side(-1, 4) is None


def test_switching_a_weapon_says_only_what_changed():
    name = {541: "Throwing Daggers", 491: "Wooden Shield", 3: "Battle Axe"}.get
    assert battle.held_words((541, 491), name) == "Throwing Daggers, Wooden Shield"
    assert battle.held_words((3, 491), name, before=(541, 491)) == "Battle Axe"
    assert battle.held_words((3, None), name, before=(3, 491)) == "no shield"
    assert battle.held_words((None, None), name, before=(3, None)) == "weapon put away"


def test_team_fields_are_small_numbers_that_differ():
    group = [agent(0x200, 45, 45, 45, 0x300, 0), agent(0x200, 45, 45, 45, 0x300, 1)]
    assert battle.small_int_fields(group) == {0x300: [0, 1]}
