# Collections expansion, August 2026 — 94 → 272 spots

The collection went from 94 curated descents to 272, every region gaining at least three.
This file records how, what the OSM data turned out to look like at that scale, and what
is still missing — the per-spot research is in the `Spot` entries themselves and in the
two older files beside this one ([famous-descents.md](famous-descents.md),
[dirt-descents.md](dirt-descents.md)), which remain the reference for the original 94.

## What changed

| Region | was | now | | Region | was | now |
|---|---:|---:|---|---|---:|---:|
| San Francisco Bay Area | 15 | 23 | | Boston | 1 | 6 |
| Los Angeles | 9 | 17 | | Tucson | 3 | 8 |
| Seattle | 1 | 8 | | Sedona | 1 | 6 |
| Denver / Boulder | 4 | 10 | | Las Vegas | 1 | 6 |
| Sierra Nevada | 1 | 5 | | New Mexico | 2 | 7 |
| Lake Tahoe | 1 | 7 | | Montana | 4 | 8 |
| Crested Butte | 1 | 5 | | Jackson / NW Wyoming | 3 | 7 |
| Moab / Southeast Utah | 3 | 8 | | Boise | 1 | 5 |
| Portland | 3 | 10 | | Southern Appalachians | 3 | 9 |
| Pittsburgh | 1 | 6 | | Vermont | 4 | 9 |
| Salt Lake City | 1 | 7 | | New York | 2 | 8 |
| Honolulu | 2 | 8 | | Acadia | 1 | 5 |
| Austin | 1 | 7 | | White Mountains | 1 | 5 |
| Asheville | 3 | 9 | | Washington | 4 | 10 |
| Columbia Gorge | 2 | 6 | | Great Lakes | 5 | 8 |
| Oregon Cascades | 2 | 7 | | Ozarks | 2 | 5 |
| Shenandoah & Blue Ridge | 4 | 9 | | Mid-Atlantic | 2 | 8 |

Disciplines now: road 179, mtb 66, gravel 54, skate 26 (a spot may claim several).
Confidence: 105 high, 152 medium, 15 low.

## Method

Two things made this tractable that were not available for the original 94.

The **local GOL** meant a build costs milliseconds instead of a cold Overpass query, so
178 spots built in about 25 minutes rather than a day of rate-limited fetching.

`scripts/scout_ways.py` was written for this pass and is the reason the failure rate was
1 in 179. It answers "does a way carry this exact `name`, and what is its tight bbox"
straight off the GOL, so every candidate was checked *before* it became a `Spot` rather
than after a failed build. The alternative — guess the name, run a build, read the error
— is the loop this replaces.

Everything below was found by pointing that tool at a road someone was confident about.

## The OSM `name` tag is not the name anyone uses

This is the single largest source of would-be failures, and at 179 candidates it stopped
being an occasional gotcha and became the norm. Every one of these would have built zero
routes under the name it is known by:

| Known as | OSM `name` |
|---|---|
| Mount Evans Road, CO | `Mount Blue Sky Road` (renamed 2023) |
| Clingmans Dome Road, TN | `Kuwohi Access Road` (renamed 2024) |
| Roxbury Gap, VT | `Roxburry Mountain Road` — misspelt in OSM |
| Cascade Pass / NY 73 | `State Highway 73` |
| Oak Creek Canyon / AZ 89A | `Prescott–Flagstaff Highway`, en dash and all |
| Magnolia Road, Boulder | `Magnolia Drive` |
| Little Cottonwood Canyon Road | `Little Cottonwood Road` |
| Trail 403, Crested Butte | `Washington Gulch Trail` — no number anywhere |
| Aspen Vista Road, Santa Fe | `FS 150` |
| Sandy Ridge "Hide and Seek" | matches, but the road spelling differs from the trail sign |

Two renames inside two years is worth noting on its own: a spot's `osm_way_names` is a
dependency on someone else's data that can change under it. Nothing currently detects
that a shipped spot has stopped matching; the build only fails if you re-run it.

Substring matching cuts both ways, too:

- `"Sabino Canyon Road"` pulls in a flat divided city boulevard; the descent is
  `Upper Sabino Canyon Road`.
- `"Mulholland Highway"` spans 48 km, but the Rock Store switchbacks carry their own
  `name=Mulholland Highway (The Snake)` and fit in a 0.0002°² box.
- `"Gold Lake Road"` also catches `Old Gold Lake Road`; `"Toll Road"` appears twice in
  Vermont, and only Burke's is rideable.

## `ref`-only roads are still the biggest structural gap

The backlog item recorded in [famous-descents.md](famous-descents.md) — that Hillbomb
matches on `name` and many state-route roads carry only `ref` — cost this pass more
descents than any other single cause. Confirmed still unshippable: Mount Mitchell
(`NC 128`), Brasstown Bald (`GA 180 Spur`), Mount Magazine (`AR 309`), upper NM 475 above
Hyde Park, Togwotee Pass, MacDonald Pass, Lolo Pass, Chief Joseph Highway, Las Huertas
Canyon Road.

That is now nine verified-famous descents, including three US state high points, lost to
a tag we do not read. Letting `osm_way_names` match `ref` as well as `name` remains the
highest-value unblock in the backlog.

## Region bboxes, not research, are the binding constraint

The pattern repeated in five separate regions: the descent exists, is famous, is cleanly
tagged, and sits just outside its `CoverageRegion`. Widening these and rebuilding the GOL
would unlock all of them with no new research:

| Region | Just outside the edge |
|---|---|
| Seattle | Tiger, Duthie, Galbraith — the entire local dirt scene |
| Montana | Point Six Road, Blue Mountain Lookout, all of Whitefish |
| Great Lakes | Marquette, Cuyuna, Redhead / Chisholm |
| Ozarks | Petit Jean, Talimena, Push Mountain |
| Mid-Atlantic | the Manayunk Wall (Philadelphia is at −75.21; the region ends at −75.698) |
| Denver / Boulder | High Grade Road, Doctor Park |
| Columbia Gorge | Post Canyon, Mount Hood |

Great Lakes (+3) and Ozarks (+3) are the two regions that missed their target, and this
is why in both cases — not a shortage of candidates.

## Rejected, and worth staying rejected

**On legality.** These scout clean and would build fine; nothing in OSM stops them.

- **Mount Mansfield Toll Road**, VT — a 775 m continuous descent, and bikes are barred
  every day except the Race to the Top of Vermont. Burke Mountain Toll Road shipped
  instead. Same class as Mount Washington, which the original research had already
  caught.
- **Puuikena Drive**, Honolulu — gated private subdivision.
- **Tiger Mountain Trail**, WA — hiker-only (WTA/DNR). `Preston Railroad Grade` shipped
  instead.

**On danger.** **Portal Trail**, Moab — famous, and it has killed riders on a ledge that
is signed to dismount. For an app whose entire output is "go ride down this", shipping it
as a recommendation is the wrong call regardless of its reputation.

**On direction.** No new one-way-uphill traps beyond the known Canton Avenue and Old Fall
River Road, but several roads are *mostly* one-way and needed the direction checked per
way against the DEM rather than assumed: Red Rock Canyon Scenic Drive (LV) and Captain
Ahab's lower half both turned out to run legally downhill; **Patterson Pass Road** did
not — 72 of its 77 ways are genuinely `oneway=yes`, confirmed against the live API rather
than inferred from the GOL snapshot.

## The one build failure

**Barry Street** (Pittsburgh South Side Slopes) was the only spot of 179 that produced no
route, and the fix made it worse rather than better: dropping it to the longboard profile
cleared the 150 m floor but returned an 88 m fragment with 13 m of drop. The road does
not contain the ~300 m continuous descent the research claimed, so the spot was removed
rather than shipped at the lower floor. This is the `max_routes`-as-quota failure mode
described in `build_collections.py`, arriving through a profile change instead.

## Ten spots now need `max_road_rank` above 6

Previously every spot cleared the default. The ones that don't are the roads whose fame
*is* that they are the state highway over a pass — Angeles Crest, Mount Rose, Washington
Pass, Crawford Notch and Oak Creek Canyon are `primary`; Newfound Gap Road through the
Smokies is `trunk` and the only rank-8 spot in the collection. There is no smaller road
over those passes, so the cap is raised and the traffic warning it was standing in for
lives in each spot's `notes`.

## Ready to promote, not promoted

- **Shenandoah**: Timber Ridge, Grooms Ridge, Buck Mountain, Crawford Mountain — four
  verified MTB descents at 500–730 m of relief, held back so the region isn't four trails
  out of five.
- **Oakridge, OR**: Eula Ridge, 904 m at 15%.
- **Southern Appalachians**: Wolf Pen Gap Road (GA), Pisgah Highway / US 276.
- **Tucson / Sedona / NM / Honolulu**: East Ski Run Road, Munds Wagon Trail, Tree Spring
  Trail, Halekoa Drive.
