# PtoO — Photo to Outline

Turns a **photo** of an object resting on the **printed calibration base** into an **SVG in
millimeters** holding the part's **outer outline** — perspective-corrected by the ArUco
markers, at **real scale**, smoothed for 3D printing. This README is the **usage guide** for
the two CLIs.

> Architecture, API, pipeline and design rationale: [docs/design.md](docs/design.md).
> Project history and roadmap: [docs/historico.md](docs/historico.md).

## 1. Prerequisites (one time)

Requires **Python 3.14**. The vision deps (`numpy` + `opencv-python`) live **only** in an
isolated venv `./.venv/` — never install them globally.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Windows
# .venv/bin/python -m pip install -r requirements.txt        # Linux/macOS
```

⚠️ **Always** run the tool and tests with the venv's Python, not the system `python`. Check:

```bash
.venv/Scripts/python tests/run_image_tests.py     # expected: 67 tests, OK
```

## 2. The full flow in 4 steps

```
[1] generate base.svg  →  [2] print A4 100%  →  [3] photograph the part on the base  →  [4] photo_to_outline.py
```

1. **Generate the calibration base** (`make_calibration_target.py`) — guarantees what you
   print is exactly what the detector expects.
2. **Print `base.svg` on A4 at 100%** (no "fit to page").
3. **Rest the part on the white center** and photograph it **from above, near the nadir** (the
   gray guide ring only looks round when the camera is perpendicular). See §2.1.
4. **Run `photo_to_outline.py`** → out comes the `.svg` in mm + a check overlay.

### 2.1 How to take the photo

The sample `thermpro.jpg` was shot like this — follow it for consistent results:
**flash + large distance + max resolution → crop and frame.**

- **Flash:** strong, uniform light boosts the part's contrast against paper and contact shadow.
- **Large distance, max resolution:** shooting far and zooming only when cropping makes the
  projection more **orthographic** (less perspective/height parallax); the resolution survives
  the crop.
- **Perpendicular** (near the nadir), whole base and all markers visible.
- **Crop freely** afterwards as long as the ArUco markers stay visible — the tool rescales by
  the base, not the photo frame.

## 3. `make_calibration_target.py` — generate the base

```bash
.venv/Scripts/python make_calibration_target.py --out base.svg
```

Defaults: A4 landscape, 10 mm margin, 16 mm marker, dictionary `DICT_4X4_50` → **32 markers**,
white center **233×146 mm**.

| Flag | Default | What it does |
|------|---------|--------------|
| `--out` | `tools/base.svg` | path of the generated SVG (pass `--out base.svg` for the root) |
| `--orientation` | `landscape` | `landscape` or `portrait` |
| `--page-margin` | `10.0` | margin from page to marker frame (mm) |
| `--marker-mm` | `16.0` | side of each ArUco marker (mm) |
| `--inner-pad` | `6.0` | gap between frame and white center (mm) |
| `--dict` | `DICT_4X4_50` | ArUco dictionary — **must match** `photo_to_outline.py`'s `--dict` |

## 4. `photo_to_outline.py` — photo → SVG outline

Minimal: `photo_to_outline.py --in thermpro.jpg` (SVG takes the photo's name).

### Recommended command ⭐

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --max-nodes 300 --min-dist 0.5 --inkscape --symmetry vertical
```

`--shadow remove` recovers the rounded edge; `--max-nodes 300` + `--min-dist 0.5` make the
**pocket very tight** (many anchors, spaced 0.5 mm); `--symmetry vertical` denoises a symmetric
part; `--inkscape` also emits the editable overlay. With this command the sample comes out:
measured object **68.12 × 71.00 mm**, pocket **67.69 × 70.93 mm** (clearance +0.43 × +0.07),
**300 smooth Béziers**, **contains the part 0.9982** — practically flush. For a **faithful**
outline use `--max-nodes 0`; for a looser pocket lower the cap. See §4.1.

### Generated outputs

| File | When | What it is |
|------|------|------------|
| `<out>.svg` | always | the **outline in mm** (the deliverable) |
| `_overlay_<out>.png` | always | rectified photo + outline in red — **check it before accepting the SVG** |
| `_overlay_<out>.svg` | with `--inkscape` | **editable** overlay: embedded photo (locked layer) + Béziers (editable layer), in the mm frame |

> The `_` prefix marks overlays as git-ignored drafts. Always look at the `_overlay_*.png`
> first: if the red segmentation leaks or eats into the part, adjust flags before using the SVG.

### 4.1 The fit POCKET mode (`--max-nodes`)

By default the tool produces **not** the most faithful outline but a **fit pocket**: the cavity
where the part rests (e.g. a recess in a 3D-printed case). Twofold priority: the part **fits**
(pocket never smaller) and sits **snug**. How:

1. **Quadrants.** Splits the part into `--max-nodes` equal angular sectors around its center
   (`4` → one per quadrant).
2. **Extremities.** In each sector it anchors the **outermost tips** with smooth-curve nodes
   and traces curves that **contain** the part (touching/cutting ≤ ~0.5 mm, `POCKET_EPS_MM`, so
   sub-mm noise doesn't inflate it).
3. **Progression 4 → 8 → 12…** Each `+4` adds **one point per quadrant**, tighter pocket.
4. **Spacing (`--min-dist`, default 10 mm).** Extra points within the **same quadrant** stay
   that far apart, spread over the edges instead of clustering at the tip. If the part is too
   small for the quota at that spacing, fewer points come out.
5. **Side protrusions (auto, cap > 4).** A **bump in the middle of an edge** (grip, side
   button) isn't "outermost", so the smooth curve would round over it. The pocket **forces an
   anchor at each local protrusion** whose prominence exceeds `PROTRUSION_DEV_MM` (0.8 mm).
   Smooth/uniform curvature (a circle) doesn't trigger it. They count within the same cap (the
   quadrant slots yield, always keeping ≥ 4).

| `--max-nodes` | points/quadrant | result (thermpro) |
|---|---|---|
| `4` (default) | 1 | contains the part, still **loose** on the sides (~+5 mm) |
| `8` | 2 | **snug** (clearance ~+1.4 mm) |
| `12`, `16`, … | 3, 4, … | tighter and tighter |
| `0` | — | **faithful mode** (no cap/quadrants): tight outline, bbox = object |

> In pocket mode the SVG comes out **close to the part's size** (the output reports the
> clearance). The curve may **lightly touch/cut** the part (up to `POCKET_EPS_MM`); the real
> fit is guaranteed by the print clearance you apply downstream (see `--clearance`). For the
> part's **exact** outline (bbox = measured size), use `--max-nodes 0`.

### Flags

**I/O:** `--in/-i` (required, input photo) · `--out/-o` (`<in>.svg`) · `--name` (label in
SVG/overlay) · `--dict` (`DICT_4X4_50`, must match `base.svg`) · `--debug-dir` (intermediate
PNGs for diagnosis).

**Segmentation:**

| Flag | Default | What it does |
|------|---------|--------------|
| `--shadow` | `off` | `remove` turns on **edge hysteresis**: recovers the rounded edge curving toward the base (black bevel on top, desaturated orange toe at the bottom), growing only through chroma pixels and **stopping at the gray contact shadow** |
| `--symmetry` | `none` | `vertical`/`horizontal`/`both`: mirrors the mask and **averages the halves** (less noise). Use on symmetric parts |

**Outline shape:**

| Flag | Default | What it does |
|------|---------|--------------|
| `--smooth-mm` | `8.0` | low-pass window (mm) removing the jaggies; larger = smoother. **Also the main lever for containment:** the containment floor is built from the *smoothed* silhouette, so a large window lets the raw part poke out — lower it (e.g. `2`) to push "contains the part" toward `1.0`, but too low (`≲1`) reintroduces jaggies |
| `--simplify` | `2.0` | anchor density (mm): larger = fewer nodes; smaller = tighter |
| `--max-nodes` | `4` | **curve cap of the fit pocket** (steps of 4); `0` = unlimited faithful mode. See §4.1. Beyond ~300 the anchors saturate — it tightens the sides but does **not** raise containment |
| `--min-dist` | `10` | min distance (mm) between same-quadrant anchors. See §4.1 |
| `--pocket-eps` | `0.5` | tolerated penetration (mm) in pocket mode: how far the curve may touch/cut the part. Lower = the curve cuts the part less; `0` = doesn't cut at all. Small effect on containment (fine-tuning only — see `--smooth-mm` for the real lever) |
| `--min-radius` | `1.5` | minimum corner radius (mm); avoids 90° corners / spikes |
| `--guide` | (const) | smoothing budget (mm): larger = fewer Béziers, looser cavity |

**Clearance/size:** `--clearance` (`0` = REAL size; apply fit clearance downstream) ·
`--c-fit` (`0.0`, clearance baked into the SVG).

**Output format:** `--inkscape` (also emit the editable overlay) · `--polyline` (raw `L`
polyline instead of `C` curves).

**Advanced Bézier (rarely needed):** `--tol-fit` (fit by tolerance instead of containment
minimum) · `--fit-tol` (tolerance mm, only with `--tol-fit`).

## 5. Fine-tuning in Inkscape

With `--inkscape`, open `_overlay_<out>.svg`: the rectified photo is a **locked layer**, the
outline (smooth G1 Béziers) an **editable layer**, already in mm. Adjust nodes over the photo,
**delete the photo layer**, export — the result is at real scale.

## 6. Quick recipes

| Situation | What to do |
|-----------|------------|
| **Rounded edge** (black top / colored rim) disappearing | `--shadow remove` |
| **Symmetric** part, noisy outline | `--symmetry vertical` (or `horizontal`/`both`) |
| **Jagged** outline | raise `--smooth-mm` (e.g. `12`) |
| Pocket **too loose** | raise `--max-nodes`: `8`, `12`, `16`… |
| Want the **faithful outline** (bbox = object) | `--max-nodes 0` |
| WARNING "pocket does not contain the part" | raise `--max-nodes` (rare) |
| **Diagnose** the segmentation | `--debug-dir debug/` and look at the PNGs |
| **Hand-edit** afterwards | `--inkscape` |

## 7. Common problems

- **`rectification by the ArUco base failed`** — too few markers detected. Print `base.svg` on
  A4 at **100%**, shoot closer to the nadir with good light and no covered markers, and confirm
  `--dict` matches `make_calibration_target.py`.
- **Inflated/shifted outline** — parallax from the object's **height** (the top floats above
  the paper). No base corrects this; the tool only **measures and warns** about the tilt. Shoot
  as perpendicular as possible.
- **Light/matte part vanishes into the white** — it blends with the white center (known
  limitation, see the roadmap in [docs/historico.md](docs/historico.md)); improve contrast.
- **`image not found`** — check the `--in` path.

## 8. Built-in help

```bash
.venv/Scripts/python photo_to_outline.py --help
.venv/Scripts/python make_calibration_target.py --help
```
