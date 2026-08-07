"""
Tests for spots.py — validation of the curated Spot data itself.

These are data tests, not logic tests. Spot definitions are hand-researched (bboxes
and OSM names transcribed from maps and cycling sites), which is exactly the kind of
data that acquires typos silently: a transposed coordinate or an unknown rider profile
would otherwise surface as a confusing runtime failure deep in a 30-second build.

What these CAN'T check is whether a bbox actually contains its road, or whether
`osm_way_names` matches OSM. Only a real build proves that — see build_collections.py,
which fails loudly and specifically when it doesn't.
"""

import pytest

from ..config import DISCIPLINES, HIGHWAY_RANK, RIDER_PROFILES, SURFACE_CATEGORIES
from ..spots import SPOTS, Spot, by_city, by_slug, cities

# The vocabulary lives in config so the UI labels and the data share one source.
_DISCIPLINES = set(DISCIPLINES)
_CONFIDENCES = {"high", "medium", "low"}


def test_spots_is_not_empty():
    assert SPOTS, "SPOTS is empty — the Collections tab would have nothing to show."


def test_slugs_are_unique():
    slugs = [s.slug for s in SPOTS]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    assert not dupes, f"Duplicate slugs (they key the JSON and the URL): {dupes}"


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_slug_is_kebab_case(spot: Spot):
    assert spot.slug == spot.slug.lower(), f"{spot.slug}: slugs must be lowercase"
    assert " " not in spot.slug, f"{spot.slug}: slugs must not contain spaces"
    assert "_" not in spot.slug, f"{spot.slug}: use kebab-case, not snake_case"


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_bbox_is_well_formed(spot: Spot):
    south, west, north, east = spot.bbox
    assert -90 <= south < north <= 90, f"{spot.slug}: bad lat range {south}..{north}"
    assert -180 <= west < east <= 180, f"{spot.slug}: bad lon range {west}..{east}"


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_bbox_is_tight(spot: Spot):
    """A loose bbox means a slow build and a rude Overpass query.

    The cost being guarded is the Overpass fetch, which scales with the *area* of the
    box, so that is what is capped. This used to be a flat 0.1° cap on each axis, on
    the reasoning that no single named descent needs 11 km — true of a named road
    climb, and false the moment trails arrived. A point-to-point descent really does
    run 14 km in one direction: the Downieville Downhill chains five trails, and
    Porcupine Rim runs the length of a mesa. Those are long thin corridors, not big
    boxes — Downieville's area is 0.0093°², against 0.0069°² for Glendora Mountain
    Road, which passed the old test comfortably.

    A per-axis cap stays, an order of magnitude looser, because it still catches the
    error the original was really aimed at: a dropped or mistyped digit, which blows
    out one coordinate rather than gently enlarging the box.
    """
    south, west, north, east = spot.bbox
    area = (north - south) * (east - west)
    assert area <= 0.02, (
        f"{spot.slug}: bbox covers {area:.4f}°² (~{(north - south) * 111:.0f} x "
        f"{(east - west) * 88:.0f} km). Tighten it — we fetch the entire road network inside it."
    )
    assert north - south <= 0.5 and east - west <= 0.5, (
        f"{spot.slug}: bbox spans {north - south:.3f}° lat x {east - west:.3f}° lon. "
        f"That is far larger than any descent — check for a mistyped coordinate."
    )


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_bbox_is_in_the_united_states(spot: Spot):
    """Rough continental-US + Hawaii/Alaska sanity check.

    Catches the classic transcription errors: a dropped minus sign on longitude puts
    the spot in China, and swapped lat/lon puts it in the ocean.
    """
    south, west, north, east = spot.bbox
    assert -180 <= west < -66, f"{spot.slug}: longitude {west} is outside the US — sign error?"
    assert 18 <= south <= 72, f"{spot.slug}: latitude {south} is outside the US — lat/lon swapped?"


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_required_text_fields_are_present(spot: Spot):
    assert spot.name.strip(), f"{spot.slug}: name is empty"
    assert spot.city.strip(), f"{spot.slug}: city is empty (it's the UI grouping key)"
    assert len(spot.state) == 2, f"{spot.slug}: state must be a 2-letter code, got {spot.state!r}"
    assert spot.state.isupper(), f"{spot.slug}: state must be uppercase, got {spot.state!r}"
    assert spot.blurb.strip(), f"{spot.slug}: blurb is empty — it's the whole point of curation"


BLURB_MAX_CHARS = 140


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_blurb_is_short(spot: Spot):
    """The blurb renders as 11px gray text on a card that already shows the numbers.

    It has one job — "is this the one I click" — and it competes for that job with
    distance, descent, top speed and flow grade sitting right above it. Long blurbs
    lose: they push the card to six lines of the least-readable text on it. 140 chars
    is about two lines in the sidebar. Put hazards, legality and closures in `notes`,
    which renders as its own callout on the spot page.
    """
    assert len(spot.blurb) <= BLURB_MAX_CHARS, (
        f"{spot.slug}: blurb is {len(spot.blurb)} chars, over the {BLURB_MAX_CHARS} cap. "
        f"Cut it to where it is + what the descent is like; move caveats to `notes`."
    )


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_osm_way_names_are_usable(spot: Spot):
    assert spot.osm_way_names, f"{spot.slug}: osm_way_names is empty — nothing to filter routes by"
    for name in spot.osm_way_names:
        assert name.strip(), f"{spot.slug}: blank entry in osm_way_names"
        assert name == name.strip(), (
            f"{spot.slug}: {name!r} has surrounding whitespace; it's matched as a substring"
        )


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_enum_fields_are_valid(spot: Spot):
    assert spot.disciplines, f"{spot.slug}: disciplines is empty — the spot is for nobody"
    unknown = set(spot.disciplines) - _DISCIPLINES
    assert not unknown, (
        f"{spot.slug}: unknown discipline(s) {sorted(unknown)}; valid: {sorted(_DISCIPLINES)}. "
        f"The Collections filter derives its chips from these, so a typo becomes a chip."
    )
    assert len(set(spot.disciplines)) == len(spot.disciplines), (
        f"{spot.slug}: duplicate entries in disciplines={spot.disciplines}"
    )
    assert spot.confidence in _CONFIDENCES, f"{spot.slug}: bad confidence {spot.confidence!r}"
    assert spot.rider_profile in RIDER_PROFILES, (
        f"{spot.slug}: unknown rider_profile {spot.rider_profile!r}; "
        f"valid: {sorted(RIDER_PROFILES)}"
    )


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_pipeline_overrides_are_valid(spot: Spot):
    assert spot.max_road_rank in set(HIGHWAY_RANK.values()), (
        f"{spot.slug}: max_road_rank={spot.max_road_rank} matches no HIGHWAY_RANK tier"
    )
    assert spot.max_routes >= 1, f"{spot.slug}: max_routes must be >= 1"
    if spot.allowed_surface_categories is not None:
        unknown = set(spot.allowed_surface_categories) - set(SURFACE_CATEGORIES) - {"unknown"}
        assert not unknown, f"{spot.slug}: unknown surface categories {unknown}"


@pytest.mark.parametrize("spot", SPOTS, ids=lambda s: s.slug)
def test_multi_name_spots_do_not_pin_to_one_road(spot: Spot):
    """stay_on_initial_road contradicts listing several road names.

    A descent that legitimately changes name can't also be constrained to the name it
    started on — the toggle would cut it off at the boundary and the extra names would
    never match. Catching this here saves a confusing 'route is mysteriously short'.
    """
    if len(spot.osm_way_names) > 1:
        assert not spot.toggles.stay_on_initial_road, (
            f"{spot.slug} lists {len(spot.osm_way_names)} road names but sets "
            f"stay_on_initial_road=True, which stops the descent at the first name change. "
            f"Set it False, or list only the road the descent starts on."
        )


# ── Lookup helpers ────────────────────────────────────────────────────────────

def test_by_slug_finds_and_misses():
    assert by_slug(SPOTS[0].slug) is SPOTS[0]
    assert by_slug("no-such-spot") is None


def test_by_city_is_case_insensitive():
    city = SPOTS[0].city
    assert by_city(city.upper()) == by_city(city.lower()) != []


def test_cities_are_distinct_and_in_spots_order():
    result = cities()
    assert len(result) == len(set(result)), "cities() returned duplicates"
    # Curation order is intentional, so cities must appear in first-seen SPOTS order.
    first_seen = []
    for s in SPOTS:
        if s.city not in first_seen:
            first_seen.append(s.city)
    assert result == first_seen
