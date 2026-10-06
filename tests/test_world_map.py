"""The map list's wording: directions use the map's axes (+x east, +y north)."""
from mbaccess.world_map import Spot, compass, describe


def test_compass_follows_the_map_axes():
    assert compass(1, 0) == "east"
    assert compass(0, 1) == "north"
    assert compass(-1, -1) == "south-west"
    assert compass(1, -0.2) == "east"       # nearly east is east


def test_describe_puts_distance_before_kingdom():
    town = Spot(5, 0, "Jelkala", "town", 0.0, 18.0, "Kingdom of Rhodoks")
    assert describe(town, (0.0, 0.0)) == "Jelkala, town, 18 north, Kingdom of Rhodoks"
    looters = Spot(9, 0, "Looters", "", 0.2, 0.0, "Outlaws", troops=7)
    assert describe(looters, (0.0, 0.0)) == "Looters, 7 troops, here, Outlaws"
