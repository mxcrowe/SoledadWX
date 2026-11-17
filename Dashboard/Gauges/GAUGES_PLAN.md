# Gauges upgrade: plan for Michael to choose from

Drafted 2026-11-13 by Fathom, while Michael was away, so the next Fable session can go straight to building. Decisions marked **(decide)** are Michael's.

## Where things stand

- The Console has four SteelSeries gauges: outside temperature, wind speed, wind direction (latest and average), and pressure. They work, but they look generic beside the barograph.
- The Gauges page (#9 in `Dashboard/PAGES_SPEC.md`) is not built yet. The spec calls it the ambient "fish tank" instrument panel.
- References in `Dashboard/Sample Gauges/`: the SteelSeries set (what we have now), the WSDL almanac panel (cream faces, script lettering, set hands), the Negretti & Zambra marine barometer (coloured bands, brass set hand, copper bezel), and steam gauges.

## The goal

A matched set of instruments as handsome as the barograph: the same brass, the same cream enamel, the same Copperplate lettering, "MOUNT SOLEDAD" on each face. It should look like one maker's set, the kind a ship's bridge or a gentleman's study would have had.

## Three ways to build them (decide)

**A. Full 3D, like the barograph.** One three.js scene, perhaps the instruments mounted on a wooden board, with baked lighting and live reflections as you turn it.
- Looks: the best; it would match the barograph exactly.
- Cost: the most work (about two Fable sessions), and a heavy page. Not suitable for the small Console cards.

**B. Photographed in Blender, hands drawn live (my recommendation).** Blender renders each instrument's still parts as images: bezel, face, glass glare. The page lays them in three layers and turns the hands live in between: face, then hands, then glass.
- Looks: photoreal from the front, since it is literally a Blender render with the hands moving. No orbiting.
- Cost: moderate (about one Fable session for the set). Light on the computer, so it works both on the Gauges page and in the Console's small cards, at any size.

**C. Drawn in 2D (vector).** Hand-drawn faces in SVG with rich styling.
- Looks: crisp and attractive, but clearly a drawing, not an object.
- Cost: the least. Could run on Opus.

## The instruments (decide which)

| Instrument | Hands | Notes |
|---|---|---|
| Barometer | pressure hand; a brass **set hand** marking the reading 3 hours ago | the gap between them is the tendency at a glance, as on the N&Z barometer |
| Thermometer | outside temperature; small tell-tale marks for today's high and low | dial, or a vertical tube like the WSDL panel |
| Hygrometer | humidity, with a second hand for dew point | the two-scale idea from the barograph's humidity paper |
| Wind dial | latest direction, and a fainter hand for the 10-minute average | compass rose face |
| Anemometer | wind speed; a tell-tale that stays at the day's top gust | knots, as the Console uses now |
| Rain gauge | today's total; rate as a small sub-dial | |

## Other choices (decide)

1. **Family look.** Brass and cream enamel to match the barograph (my suggestion), or nickel/chrome with silver faces like the N&Z barometer.
2. **Where.** The Gauges page only, or also replace the Console's four SteelSeries gauges. With approach B, both can share the same art.
3. **The Gauges page layout.** Instruments mounted on a polished wooden board, like a bridge panel, or standing on the barograph's green baize.

## Order of work, once decided

1. Draw each face (scales, lettering) in `make_textures.py` style, shared by Blender and the page.
2. Model one instrument fully, the barometer, render it, and show Michael. Adjust until he is happy.
3. Build the rest of the set from the same parts.
4. The page: layers, live hands with a gentle eased swing, set hands and tell-tales from the Archive.
5. Swap into the Console (if chosen), build, deploy, Michael checks on real data, commit.

Steps 2 and 3 are the Fable work. Steps 1, 4 and 5 can be done on Opus.
