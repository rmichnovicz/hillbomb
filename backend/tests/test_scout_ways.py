"""
Tests for the spot-research tool, `scripts/scout_ways.py`.

The tool's job is to answer the two questions that decide whether a Spot works —
"does a way carry this exact `name`" and "what is its tight bbox" — and the second
answer gets pasted straight into `spots.py`. So the bbox it prints has to satisfy the
same constraints `test_spots.py` will later enforce on the spot, and it has to be
padded: an unpadded box clips the junctions at each end, which is what tells the graph
where the descent stops.

Everything here runs on synthetic ways. The tool's OSM fetch and DEM lookup are the
pipeline's own, tested elsewhere; what is new and worth pinning is the grouping and the
geometry.
"""

import math

import pytest

from ..scripts import scout_ways
from ..types import OSMNode, OSMWay


def _straight_way(way_id: int, name: str, coords: list[tuple[float, float]], **kw) -> tuple:
    """An OSMWay plus the node dict it references, from (lon, lat) pairs."""
    nodes = {way_id * 1000 + i: OSMNode(id=way_id * 1000 + i, lat=lat, lon=lon)
             for i, (lon, lat) in enumerate(coords)}
    way = OSMWay(
        id=way_id,
        node_ids=sorted(nodes),
        highway=kw.pop("highway", "residential"),
        oneway=kw.pop("oneway", False),
        oneway_reverse=kw.pop("oneway_reverse", False),
        name=name,
        **kw,
    )
    return way, nodes


def test_haversine_matches_a_known_distance():
    # One degree of latitude is ~111.2 km anywhere on the globe.
    d = scout_ways._haversine_m((-122.0, 37.0), (-122.0, 38.0))
    assert 110_000 < d < 112_000


def test_groups_ways_by_name_and_sums_their_length():
    """A named road is many OSM ways; the tool reports the road, not the ways."""
    w1, n1 = _straight_way(1, "Conzelman Road", [(-122.50, 37.83), (-122.49, 37.83)])
    w2, n2 = _straight_way(2, "Conzelman Road", [(-122.49, 37.83), (-122.48, 37.83)])
    w3, n3 = _straight_way(3, "Bunker Road", [(-122.50, 37.84), (-122.49, 37.84)])
    nodes = {**n1, **n2, **n3}

    groups = {g.name: g for g in scout_ways._group_by_name([w1, w2, w3], nodes, None)}

    assert set(groups) == {"Conzelman Road", "Bunker Road"}
    assert len(groups["Conzelman Road"].ways) == 2
    # Two ~880 m segments end to end.
    assert groups["Conzelman Road"].length_m == pytest.approx(
        2 * groups["Bunker Road"].length_m, rel=0.01
    )


def test_name_filter_is_a_case_insensitive_substring():
    """Matching mirrors `build_collections._matches_spot`, which is a substring match.

    If the tool matched more strictly than the builder, it would report a name as
    absent that the builder would go on to accept — and vice versa, which is worse:
    a verified-looking spot that finds nothing.
    """
    w1, n1 = _straight_way(1, "Conzelman Road", [(-122.50, 37.83), (-122.49, 37.83)])
    w2, n2 = _straight_way(2, "Old Conzelman Road", [(-122.50, 37.82), (-122.49, 37.82)])
    w3, n3 = _straight_way(3, "Bunker Road", [(-122.50, 37.84), (-122.49, 37.84)])
    nodes = {**n1, **n2, **n3}

    names = {g.name for g in scout_ways._group_by_name([w1, w2, w3], nodes, ["conzelman"])}
    assert names == {"Conzelman Road", "Old Conzelman Road"}


def test_unnamed_ways_are_skipped():
    """`osm_way_names` has nothing to match on an unnamed way, so it is not a candidate."""
    named, n1 = _straight_way(1, "Conzelman Road", [(-122.50, 37.83), (-122.49, 37.83)])
    unnamed, n2 = _straight_way(2, "", [(-122.50, 37.84), (-122.49, 37.84)])

    groups = scout_ways._group_by_name([named, unnamed], {**n1, **n2}, None)
    assert [g.name for g in groups] == ["Conzelman Road"]


def test_union_bbox_contains_every_node_with_room_to_spare():
    """The printed bbox is pasted into a Spot, so it must cover the road plus a margin.

    The margin is not cosmetic: `overpass._contiguous_inbbox_runs` trims any way
    crossing the box edge, so a bbox drawn exactly on the road's endpoints loses the
    junctions that tell the graph where the descent starts and stops.
    """
    w1, n1 = _straight_way(1, "Conzelman Road", [(-122.50, 37.830), (-122.49, 37.835)])
    w2, n2 = _straight_way(2, "Conzelman Road", [(-122.49, 37.835), (-122.48, 37.828)])

    group, = scout_ways._group_by_name([w1, w2], {**n1, **n2}, None)
    south, west, north, east = group.union_bbox()

    assert south < 37.828 and north > 37.835
    assert west < -122.50 and east > -122.48
    # Padding is ~200 m, i.e. well under a hundredth of a degree on either axis.
    assert 37.828 - south == pytest.approx(scout_ways.PAD_DEG_LAT, abs=1e-5)
    assert east - (-122.48) == pytest.approx(scout_ways.PAD_DEG_LON, abs=1e-5)


def test_union_bbox_of_a_real_road_passes_the_spot_bbox_tests():
    """Whatever the tool prints has to survive `test_spots.py`'s guards.

    Those are the constraints the pasted value will actually be judged against — an
    area of 0.02°² and 0.5° per axis — so a tool that hands back something they reject
    is handing back a spot that cannot ship.
    """
    coords = [(-122.529 + 0.0025 * i, 37.8215 + 0.0007 * i) for i in range(20)]
    way, nodes = _straight_way(1, "Conzelman Road", coords)

    group, = scout_ways._group_by_name([way], nodes, None)
    south, west, north, east = group.union_bbox()

    assert (north - south) * (east - west) <= 0.02
    assert north - south <= 0.5 and east - west <= 0.5
    assert -180 <= west < -66 and 18 <= south <= 72


def test_max_rank_reports_the_cap_a_spot_would_need():
    """`max_road_rank` must clear the road's *highest* class or the spot builds nothing.

    A road that is `residential` for 10 ways and `secondary` for one still needs the
    secondary cap, so the maximum is the number to print, not the mode.
    """
    w1, n1 = _straight_way(1, "West Galer Street", [(-122.40, 47.630), (-122.39, 47.630)],
                           highway="residential")
    w2, n2 = _straight_way(2, "West Galer Street", [(-122.39, 47.630), (-122.38, 47.631)],
                           highway="secondary")

    group, = scout_ways._group_by_name([w1, w2], {**n1, **n2}, None)
    assert group.max_rank == 6  # secondary
    assert group.highways == {"residential": 1, "secondary": 1}


def test_oneway_count_covers_both_directions():
    """`oneway=-1` is still a one-way road; missing it would hide an uphill-only descent."""
    w1, n1 = _straight_way(1, "Filbert Street", [(-122.42, 37.802), (-122.41, 37.802)],
                           oneway=True)
    w2, n2 = _straight_way(2, "Filbert Street", [(-122.41, 37.802), (-122.40, 37.802)],
                           oneway_reverse=True)
    w3, n3 = _straight_way(3, "Filbert Street", [(-122.40, 37.802), (-122.39, 37.802)])

    group, = scout_ways._group_by_name([w1, w2, w3], {**n1, **n2, **n3}, None)
    assert group.oneway_count == 2


def test_untagged_surface_is_reported_as_such_not_dropped():
    """Most US residential ways carry no `surface`; silently omitting them would read
    as "no surface data at all" rather than "unsurveyed, probably asphalt"."""
    w1, n1 = _straight_way(1, "Rialto Street", [(-79.98, 40.455), (-79.98, 40.458)])
    w2, n2 = _straight_way(2, "Rialto Street", [(-79.98, 40.458), (-79.98, 40.461)],
                           surface="cobblestone")

    group, = scout_ways._group_by_name([w1, w2], {**n1, **n2}, None)
    assert group.surfaces == {"(untagged)": 1, "cobblestone": 1}


def test_a_degenerate_way_is_skipped_rather_than_dividing_by_zero():
    """A single-node way has no length and no direction — and `avg_grade` divides by it."""
    way = OSMWay(id=1, node_ids=[1], highway="residential", oneway=False,
                 oneway_reverse=False, name="Stub Street")
    nodes = {1: OSMNode(id=1, lat=37.8, lon=-122.4)}

    assert scout_ways._group_by_name([way], nodes, None) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--bbox", "37.8,-122.5,37.9"],                     # three numbers
        ["--bbox", "37.9,-122.5,37.8,-122.4", "--list"],    # north below south
        ["--bbox", "37.8,-122.4,37.9,-122.5", "--list"],    # east west of west
        ["--bbox", "37.8,-122.5,37.9,-122.4"],              # neither --name nor --list
    ],
)
def test_bad_arguments_exit_rather_than_query(argv):
    """Coordinate-order mistakes are the classic transcription error here.

    Left unchecked, a swapped bbox is not an error but an empty result, which reads as
    "that road is not in OSM" — the one conclusion this tool exists to prevent someone
    reaching by mistake.
    """
    with pytest.raises(SystemExit):
        scout_ways.main(argv)


def test_elevation_stats_are_one_query_for_every_group(monkeypatch):
    """A DEM read is per-tile-window, not per-point, so batching is the whole game.

    Calling the service once per road would re-read the same tile for every road in
    the box — the exact mistake `_Dep13TileCache` exists to avoid — and `--list` over a
    metro asks about dozens of roads at once.
    """
    w1, n1 = _straight_way(1, "Alpha Road", [(-122.50, 37.83), (-122.49, 37.83)])
    w2, n2 = _straight_way(2, "Beta Road", [(-122.48, 37.84), (-122.47, 37.84)])
    groups = scout_ways._group_by_name([w1, w2], {**n1, **n2}, None)

    calls = []

    class FakeService:
        def get_elevations(self, coords):
            calls.append(list(coords))
            # Ascending, so each road's own min/max is unambiguous.
            return [100.0 * i for i in range(len(coords))]

    stats = scout_ways._elevation_stats(groups, FakeService())

    assert len(calls) == 1, f"expected one batched DEM query, got {len(calls)}"
    assert set(stats) == {"Alpha Road", "Beta Road"}
    for name in stats:
        lo, hi, drop = stats[name]
        assert drop == pytest.approx(hi - lo)
        assert not math.isnan(drop)
