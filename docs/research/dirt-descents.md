# Famous US Dirt Descents — research for Hillbomb Collections

**Companion to [famous-descents.md](famous-descents.md), which covers pavement.** Every OSM name,
`highway` tag and bbox below was verified against live Overpass on 2026-08-06.

> Covers the **original 94 spots**. The August 2026 expansion to 272 — which added 120
> dirt and gravel spots and answered the "no Pacific Northwest, Southeast or Northeast
> dirt" gap noted at the bottom of this file — is in
> [expansion-2026-08.md](expansion-2026-08.md).

---

## Method

Same as the paved research: candidates came from riding reputation, then each was checked against
the live Overpass API rather than guessed at from the popular name. The query was a
case-insensitive name regex over a generous region bbox, returning tags and geometry:

```
[out:json][timeout:90];
way["highway"]["name"~"<candidate>",i](<region bbox>);
out tags geom;
```

`bbox` values below are the **union bbox of the matched ways**, padded ~200 m. Nothing is invented.

Two tags were captured that the paved research had no reason to look at:

- **`mtb:scale`** — the 0–6 Singletrail-Skala. This is the one riders actually tag.
- **`sac_scale`** — the hiking difficulty scale, used as a fallback where `mtb:scale` is absent.

See `config.SAC_SCALE_TO_DIFFICULTY` for how the two are folded into one number, and why the
mapping is a conservative upper bound rather than a translation.

---

## The finding that mattered most

**The single blocking gap was `highway=track`.** It was absent from `config.HIGHWAY_RANK`, and
`overpass.ROAD_NETWORK_TYPES` derives from that dict, so the Overpass query never asked for it.
Nothing downstream can route onto a way that was never downloaded.

That one missing key is most of what "the pipeline can't reach dirt" meant. Of the eleven spots
promoted below, **six are `highway=track`** — including Repack, the road mountain biking was
invented on. `path` and `cycleway` were already in the table, which is why singletrack (Saxon
Creek, Trail 401) was reachable in principle all along while fire roads were not.

## The second finding: difficulty coverage is thin

Of the ways checked, roughly **half carry `mtb:scale` and almost none carry both tags**. Untagged is
the norm, not the exception, even on trails as well known as Butcher Ranch.

This is why `mark_traversable`'s difficulty cap lets untagged ways *through* rather than excluding
them — the opposite of what the surface filter does with `unknown`. Excluding unknowns would empty
the graph on most trail spots. The consequence, stated plainly because it limits what the feature
can claim: **the difficulty filter can narrow a search already on trails; it cannot guarantee a road
search never sees singletrack.** Pinning `osm_way_names` is what does that job.

Where a trail *is* graded, the number is informative and worth showing. Where it isn't, `null` means
unknown and must never render as a grade of 0.

---

## Promoted to `spots.py` (11)

| Spot | OSM name(s) | `highway` | surface | `mtb:scale` | Notes |
|---|---|---|---|---|---|
| Repack | `Cascade Fire Road`, `Cascade Fire Road / Repack` | `track` | untagged | — | Two ways; the shorter substring catches both |
| Old Railroad Grade | `Old Railroad Grade Fire Road` | `track` | dirt/gravel/**paved** | — | Mixed surface, incl. one paved stretch |
| Switzerland Trail | 4 name variants¹ | `track`, `unclassified`, `residential` | unpaved/dirt | 1 (partial) | Also carries `sac_scale=hiking` on some ways |
| Lickskillet Road | `Lickskillet Road` | `residential`, `unclassified` | compacted/unpaved | — | ~1 km, all of it steep |
| Mount Wilson Toll Road | `Mount Wilson Toll Road` | `service`, `track` | paved + unpaved | — | `sac_scale=hiking` on part |
| Trail 401 | `Trail 401`, `Trailriders 401 Trail` | `path`, `track` | ground | 3 | Also `sac_scale=mountain_hiking` → max() picks 3 |
| Downieville Downhill | 5 trails² | `path` | dirt | 0–1 | Grades read far easier than the trail's reputation |
| Mr. Toad's Wild Ride | `Saxon Creek Trail` | `path` | dirt | 3 | One unbroken way for the whole descent |
| Porcupine Rim | `Porcupine Rim 4x4 Trail`, `… Single Track` | `track`, `path` | ground | 3 | Name changes mid-descent |
| Shafer Trail | `Shafer Trail` | **`secondary`** | asphalt + ground | — | Dirt road tagged `secondary`; needs rank ≥ 6 |
| Moki Dugway | `Moki Dugway` | `tertiary` | gravel | — | Only the switchbacks carry the name |

¹ `Switzerland Trail`, `South Switzerland Trail`, `Switzerland Trail Colorado and North Western Rail
Road`, `Switzerland Trail Colo. & North Western R. R.` — all caught by the substring
`"Switzerland Trail"`.

² `Sunrise Trail` → `Butcher Ranch Trail` → `Pauley Creek Trail` → `Third Divide Trail` →
`First Divide Trail`. Note `Pauley Creek Trail` is distinct from `Pauley Creek Road`
(`unclassified`, asphalt/gravel) in the same bbox — the full trail name is required so the
substring match doesn't pick up the road.

### Tag gotchas specific to dirt

- **Shafer Trail is `highway=secondary`.** A dirt shelf road in a national park, classified above
  most of the paved climbs in the collection. Any instinct to *lower* `max_road_rank` for dirt
  spots would exclude it.
- **Lickskillet is `surface=compacted`,** which `SURFACE_CATEGORIES` maps to `gravel`, not
  `unpaved`. A surface filter written as `{"unpaved"}` would drop it.
- **Old Railroad Grade and Mount Wilson Toll Road are partly paved.** Restricting dirt spots to
  unpaved surfaces would fragment both. This is why the dirt spots leave
  `allowed_surface_categories=None` and lean on `osm_way_names` instead.
- **Name changes mid-descent are the norm off pavement,** where they were the exception on road.
  Porcupine Rim, Trail 401 and Downieville all need `stay_on_initial_road=False` plus every name
  listed. Road spots keep the default.

---

## Researched, not promoted

**Old Fall River Road** (RMNP, CO) — `Old Fall River Road`, `highway=unclassified`,
`surface=dirt`, bbox `(40.41416, -105.75302, 40.44401, -105.65511)`. Correctly tagged
**`oneway=yes`, and the one-way direction is uphill** — the park runs it as a one-way ascent.
The pathfinder only traverses edges in their stored direction, so this would build zero routes,
which is the right answer: there is no legal descent to find. Left out deliberately, not by
oversight.

**The Whole Enchilada, upper half** (Moab, UT) — all four upper segments verified:
`Burro Pass` (`path`, ground, `mtb:scale=3`), `Hazard County` (`path`, ground, `3`),
`Kokopelli Trail` (`track`, ground, `2`), `Upper Porcupine Singletrack` (`path`, ground, `3`).
Not promoted for two reasons: the union bbox with Porcupine Rim is ~0.042°², roughly four times
the largest box in the collection, and the named segments are not contiguous — they are linked by
unnamed connectors and shuttle road. Porcupine Rim ships on its own as the famous last third.
Revisit if the builder ever supports a multi-bbox spot.

**Flume Trail** (Tahoe, NV) — a contouring bench trail. Famous, but it barely descends, so there is
no hill bomb in it.

---

## What this doesn't cover

- **No Pacific Northwest, Southeast or Northeast dirt.** Pisgah (Black Mountain, NC), Bellingham
  (Galbraith), and Bentonville are all unresearched. The set above is West-heavy because that is
  where the reputation-level descents cluster, but that is a curation bias worth fixing.
- **Bike-park laps** (Whistler-style lift-served flow trails) are deliberately absent. They are
  descents, but they are a different product from "find me a hill".
- **Nothing was ridden.** As with the paved research, confidence is about the OSM data being right,
  not about the trail being good. `confidence="medium"` entries are where the famous line is a
  subjective slice of a longer way, or where the OSM coverage is partial.
