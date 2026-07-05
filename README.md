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

### 1.1 Installing Python + pip on Windows

If `python --version` doesn't print `Python 3.14.x`, install it first (pick one):

- **winget** (built into Windows 10/11), from a terminal:

  ```powershell
  winget install Python.Python.3.14
  ```

- **Installer:** download **Python 3.14 (64-bit)** from
  [python.org/downloads](https://www.python.org/downloads/) and run it, ticking
  **"Add python.exe to PATH"** on the first screen.

**pip comes bundled** with Python — no separate install. Open a **new** terminal and check:

```powershell
python --version        # expected: Python 3.14.x
python -m pip --version # pip must answer
```

If `python` isn't found (or opens the Microsoft Store), the PATH wasn't set — re-run the
installer and tick the PATH option, or use the `py` launcher instead: `py -3.14` works in
every command below in place of `python`.

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
    --shadow remove --min-dist 0.6 --smooth-mm 2 --inkscape --symmetry vertical
```

`--shadow remove` recovers the rounded edge; `--min-dist 0.6` makes the **pocket very tight**
(anchors spaced 0.6 mm — smaller `--min-dist` = more anchors = tighter); `--symmetry vertical`
denoises a symmetric part; `--inkscape` also emits the editable overlay. With this command the
sample comes out: measured object **68.12 × 71.00 mm**, pocket **67.94 × 71.00 mm** (clearance
−0.18 × −0.00), **305 smooth Béziers**, **contains the part 0.9999** — practically flush. Adding
`--mask-smooth-mm 2` smooths the wavy **black** edge at the source → **303 Béziers, contains 1.0000**.
For a **faithful** outline use `--faithful`; for a looser pocket raise `--min-dist`. See §4.1.

### The whole thing in one command ⭐⭐

Add `--edit` to the recommended command and the CLI runs the full pipeline **and** drops you
into the built-in node editor before saving — detect, rectify, fit the pocket, then hand-tune
the curve over the rectified photo, all in one shot:

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --min-dist 0.6 --smooth-mm 2 --inkscape --symmetry vertical --edit
```

A tkinter window opens (no extra install) with the rectified photo as background and the curve's
nodes as draggable handles: drag to move, click the curve to insert, right-click to delete, wheel
to zoom at the cursor, **Ctrl + drag** to pan. **Finalize** is WYSIWYG — it writes the SVG from
**exactly** the curve on screen (closing without Finalize writes nothing). Needs a graphical
display; drop `--edit` to get the automatic output only. Full editor guide in §5.

### Generated outputs

| File | When | What it is |
|------|------|------------|
| `<out>.svg` | always | the **outline in mm** (the deliverable) |
| `_overlay_<out>.png` | always | rectified photo + outline in red — **check it before accepting the SVG** |
| `_overlay_<out>.svg` | with `--inkscape` | **editable** overlay: embedded photo (locked layer) + Béziers (editable layer), in the mm frame |

> The `_` prefix marks overlays as git-ignored drafts. Always look at the `_overlay_*.png`
> first: if the red segmentation leaks or eats into the part, adjust flags before using the SVG.

### 4.1 The fit POCKET mode (`--min-dist`)

By default the tool produces **not** the most faithful outline but a **fit pocket**: the cavity
where the part rests (e.g. a recess in a 3D-printed case). Twofold priority: the part **fits**
(pocket never smaller) and sits **snug**. How:

1. **Quadrants.** Splits the part into 4 angular sectors around its center.
2. **Extremities.** In each sector it anchors the **outermost tips** with smooth-curve nodes
   and traces curves that **contain** the part (touching/cutting ≤ ~0.5 mm, `POCKET_EPS_MM`, so
   sub-mm noise doesn't inflate it).
3. **Density (`--min-dist`, default 10 mm) — the one tightness lever.** There is **no node
   cap**: each quadrant takes **all** the outermost points that stay ≥ `--min-dist` apart, so the
   anchor count emerges purely from the spacing. **Smaller `--min-dist` = more anchors = tighter
   pocket and higher containment.** Lower it (e.g. `1`, `0.6`) until "contains the part" crosses
   your target; stop at the **largest `--min-dist` that still crosses** (fewer nodes is better).
4. **Side protrusions (auto).** A **bump in the middle of an edge** (grip, side button) isn't
   "outermost", so the smooth curve would round over it. The pocket **forces an anchor at each
   local protrusion** whose prominence exceeds `PROTRUSION_DEV_MM` (0.8 mm). Smooth/uniform
   curvature (a circle) doesn't trigger it.
5. **Geometric primitives (v0.10, on by default — `--line-tol`/`--arc-tol`).** Straight
   stretches of the contour become **exact straight lines** (chord shifted outward by the
   residual, so containment is guaranteed and a straight edge never bows inward) and the gaps
   between them become **tangent arcs** (a corner turns into a clean fillet, one cubic per
   90°). Interior anchors are suppressed — fewer nodes, CAD-like output — and `--min-dist`
   only governs the remaining free-form stretches. `--line-tol 0` disables both and restores
   the legacy behavior.

| `--min-dist` | result (thermpro) |
|---|---|
| `10` (default) | contains the part, **loose** on the sides |
| `1` | snug (~201 Béziers, contains 0.9998) |
| `0.6` | flush (305 Béziers, **contains 0.9999**) |
| `--faithful` | **faithful mode** (no quadrants): tight outline, bbox = object |

> **Counter-intuitive:** a **large** `--min-dist` (few anchors) makes the pocket **both looser
> and less contained** — sparse anchors give long Béziers that bow **inward** at rounded corners,
> cutting the part. To contain more, **lower** `--min-dist`.
>
> In pocket mode the SVG comes out **close to the part's size** (the output reports the
> clearance). The curve may **lightly touch/cut** the part (up to `POCKET_EPS_MM`); the real fit
> is guaranteed by the print clearance you apply downstream (see `--clearance`). For the part's
> **exact** outline (bbox = measured size), use `--faithful`.

### Flags

**I/O:** `--in/-i` (required, input photo) · `--out/-o` (`<in>.svg`) · `--name` (label in
SVG/overlay) · `--dict` (`DICT_4X4_50`, must match `base.svg`) · `--debug-dir` (intermediate
PNGs for diagnosis).

**Segmentation:**

| Flag | Default | What it does |
|------|---------|--------------|
| `--shadow` | `off` | `remove` = **edge hysteresis** by chroma: recovers the rounded edge curving toward the base (black bevel on top, desaturated orange toe at the bottom), growing only through chroma pixels and **stopping at the gray contact shadow**. `texture` = **shadow subtractor** for **gray-neutral bodies**: value grabs the dark body, then local-texture (adaptive Otsu threshold) **carves out** the smooth-and-lighter cast shadow that a plain value cut would swallow — works even over a chromatic paper background; a built-in **watershed edge refinement** then re-decides the boundary on the physical gradient, expelling the dark contact shadow (umbra) |
| `--in2` | off | **two-photo fusion** for hard sunlight shadows or bright metal parts: second photo of the same part on the same base with the light coming from the **opposite side** (rotate base+part together ~180° relative to the sun). Registration (rotation+shift) is automatic; each photo is **sovereign on its lit side**, so both shadows drop out. Also auto-enables a faint-saturation predicate that recovers **bright smooth metal** (connector tops ≈ paper brightness) that single-photo segmentation cannot see. The overlay uses the better-lit photo as background |
| `--fuse-grow` | `0.0` | only with `--in2`: optional geodesic grow (mm) within the union of both masks, for parallax residue near the bisector of the two shadow directions. Rarely needed |
| `--symmetry` | `none` | `vertical`/`horizontal`/`both`: mirrors the mask and **averages the halves** (less noise). Use on symmetric parts |
| `--level` | `off` | `auto` = **auto-levelling** (v0.12): fixes the fine rotation of a part laid slightly askew on the base — estimates the deviation from the nearest 90° via the minimum-area envelope and rotates photo+mask together (runs **before** `--symmetry`, so the v/h symmetry axis lines up). Only applies within 0.2–7°; near-square/round parts without a long straight edge are left alone (unstable envelope) |
| `--mask-smooth-mm` | `0.0` (off) | **regularizes the silhouette** before tracing: blurs the signed-distance field and re-thresholds, removing bumps/waviness smaller than the radius from the **mask** itself. Use when a low-contrast **black** edge comes out wavy even at high containment; `~1.5–2` cleans it without rounding macro corners. Orthogonal to `--smooth-mm` (which acts on the curve) and to containment |
| `--mask-smooth-keep-bumps` | off | biases `--mask-smooth-mm` toward **closing** (a closing on the distance field): removes only **concave** dents (noise) while **preserving convex bumps** (e.g. a side tab) that the isotropic mode would round off |

**Outline shape:**

| Flag | Default | What it does |
|------|---------|--------------|
| `--min-dist` | `10` | **the pocket tightness lever** (mm): min distance between same-quadrant anchors. **No node cap** — smaller `--min-dist` = more anchors = tighter pocket and higher containment. With primitives on (v0.10) it only governs the free-form stretches. See §4.1 |
| `--line-tol` | `0.3` | **straight-line detection** (mm, v0.10): a maximal stretch deviating less than this from its chord becomes one exact straight line (never bowing inward). `0` disables lines **and** arcs (legacy path). See §4.1 |
| `--arc-tol` | `0.3` | **arc detection** (mm, v0.10): in the gaps between lines, a least-squares circle within this radial residual becomes a tangent arc (corners = clean fillets). `0` disables arcs only |
| `--smooth-mm` | `8.0` | low-pass window (mm) removing the jaggies; larger = smoother. **Fine lever for containment:** the floor is built from the *smoothed* silhouette, so a large window lets the raw part poke out — lower it (e.g. `2`) to scrape the last 0.0x once `--min-dist` is close, but too low (`≲1`) reintroduces jaggies |
| `--faithful` | off | **faithful mode**: exact outline of the part (bbox = object, with snap) instead of the fit pocket. Replaces the old `--max-nodes 0`. Ignored if `--tol-fit` |
| `--simplify` | `2.0` | anchor density (mm) in **faithful** mode: larger = fewer nodes; smaller = tighter |
| `--pocket-eps` | `0.5` | tolerated penetration (mm) in pocket mode: how far the curve may touch/cut the part. Lower = the curve cuts the part less; `0` = doesn't cut at all. Small effect on containment (fine-tuning only — see `--min-dist` for the real lever) |
| `--min-radius` | `1.5` | minimum corner radius (mm); avoids 90° corners / spikes |
| `--guide` | `0.5` | smoothing budget (mm) for `--tol-fit`: larger = fewer Béziers, looser cavity |

**Clearance/size:** `--clearance` (`0` = REAL size; apply fit clearance downstream) ·
`--c-fit` (`0.0`, clearance baked into the SVG).

**Output format:** `--inkscape` (also emit the editable overlay) · `--polyline` (raw `L`
polyline instead of `C` curves) · `--edit` (open the built-in node editor before saving).

**Advanced Bézier (rarely needed):** `--tol-fit` (fit by tolerance instead of containment
minimum) · `--fit-tol` (tolerance mm, only with `--tol-fit`).

## 5. Adjust nodes in the built-in editor (`--edit`)

Detection always errs a little (shadow/glare on the edge), so you usually want a manual touch-up.
With `--edit`, the tool detects as usual and then opens a small window (tkinter, no extra install):
the **rectified photo** as background and the curve's **nodes as draggable handles**.

- **Drag** a handle to move a node · **click on the curve** to insert a node · **right-click** a
  handle to delete it · mouse wheel = **zoom at the cursor** (the point under the mouse stays put),
  **Ctrl + left-drag** = pan.
- **Re-trace** draws a smooth (G1) Catmull-Rom curve through your nodes; moving, inserting or
  deleting a node re-traces automatically. **Undo** / **Reset** as usual.
- **Shift+click** selects up to 2 nodes (red) and **Line** replaces the shortest path between
  them with an exact straight segment (neighbours leave tangent to it).
- **Symmetry** (v0.12) — with `--symmetry` from the CLI the editor opens with it ON: moving/
  inserting/deleting a node (and Line) is **mirrored** across the dashed axis; a node on the axis
  slides along it. The axis line is **draggable**, and **Mirror ◀/▶** rebuilds one side as the
  mirror of the other (pick the good side when a shadow inflated the detection — this also lets
  you turn symmetry on for a contour that came without `--symmetry`). The **V/H** selector picks
  the axis orientation when the CLI didn't.
- **Ruler** (v0.12, on by default) — mm ruler on the top/left edges (ticks adapt to zoom) plus a
  live **W×H dimension** of the object (also in the status bar) — handy for matching a caliper
  measurement while dragging the symmetry axis.
- **Rotate** (v0.12) — explicit fine-rotation mode: a dashed guide line follows the cursor;
  right-click = +0.1°, left-click = −0.1°, wheel rotates too (0.05° with Shift). Photo and nodes
  turn **together** (the SVG and overlay come out rotated — true WYSIWYG). Entering the mode
  turns Symmetry off; prefer `--level auto` for a tilted part that is also symmetric.
- **Pan** (v0.12) — Rotate's twin for fine **sideways nudging**: right-click = +0.1 mm (right),
  left-click = −0.1 mm (left), wheel too (0.05 mm with Shift), vertical guide line at the
  cursor. It shifts the **whole outline (and the symmetry axis with it)** while the photo stays
  put — fixes a uniform lateral bias of the detection (e.g. a shadow that pushed the entire
  contour to one side). Unlike Rotate it does **not** turn Symmetry off (nodes and axis move by
  the same step, so the pairing survives). Mutually exclusive with Rotate; Reset zeroes it.
- **Finalize** is **WYSIWYG**: it closes the window and writes the same outputs from **exactly the
  curve on screen** — nothing is recomputed (closing the window without Finalize writes nothing).

You place the nodes and see the curve; Finalize saves precisely that. The final `<out>.svg` is that
curve (and `_overlay_<out>.svg` too, with `--inkscape`).

## 5b. Fine-tuning in Inkscape (alternative)

With `--inkscape`, open `_overlay_<out>.svg`: the rectified photo is a **locked layer**, the
outline (smooth G1 Béziers) an **editable layer**, already in mm. Adjust nodes over the photo,
**delete the photo layer**, export — the result is at real scale.

## 5c. Automatic calibration with the `/ptoo` skill (Claude Code)

If you use [Claude Code](https://claude.com/claude-code), the repo ships a `/ptoo` **skill**
(`.claude/skills/ptoo/`) that automates the whole `run → look at the overlay → tweak a flag →
repeat` loop for you. It drives `photo_to_outline.py` from a photo toward a **snug fit pocket**,
inspecting the outline with zoom tiles over the rectified photo between runs. It never edits the
CLI — it only calibrates the flags (and, with `--debug`, *proposes* code improvements without
applying them).

```
/ptoo <photo.jpg> --pass N [--debug]
```

- `<photo.jpg>` — the input photo (a bare name resolves at the repo root).
- `--pass N` — hard cap on calibration attempts (default 3).
- `--debug` — after converging, also emit a CLI-improvement package (diagnosis + proposed
  diff + a next-version plan under `docs/melhorias/`); does **not** touch the CLI.

**Acceptance target:** the skill keeps lowering `--min-dist` (and, if needed, `--smooth-mm` then
`--pocket-eps`) until *contains the part* ≥ **0.9999**, preferring the result with the **fewest
nodes** among those that cross. It keeps a small memory (`memory.md`) of good parameters per part
size to shorten future searches, and finishes with one optional `--edit` pass for a manual
touch-up. Full behavior is documented in the skill's own [SKILL.md](.claude/skills/ptoo/SKILL.md).

> The skill is Claude-Code-only and is invoked by typing `/ptoo …` in a Claude Code session; it
> is not a shell command. Under the hood it just calls the same `photo_to_outline.py` you can run
> by hand (§4).

## 6. Quick recipes

| Situation | What to do |
|-----------|------------|
| **Rounded edge** (black top / colored rim) disappearing | `--shadow remove` |
| **Hard sunlight shadow** no `--shadow` mode fixes | second photo with opposite light + `--in2 photo2.jpg` |
| **Bright metal connector** vanishing into the white paper | same: `--in2` (auto-recovers faint metal) |
| **Symmetric** part, noisy outline | `--symmetry vertical` (or `horizontal`/`both`) |
| Part laid **slightly askew** on the base (~0.5–5°) | `--level auto` (or the editor's **Rotate** mode) |
| Shadow **inflated one side** of a symmetric part | `--edit` → Symmetry on → drag the axis → **Mirror** with the good side |
| **Jagged** outline | raise `--smooth-mm` (e.g. `12`) |
| Pocket **too loose** | lower `--min-dist`: `2`, `1`, `0.5`… |
| Want the **faithful outline** (bbox = object) | `--faithful` |
| WARNING "pocket does not contain the part" | lower `--min-dist` |
| **Diagnose** the segmentation | `--debug-dir debug/` and look at the PNGs |
| **Hand-edit** the nodes | `--edit` (built-in editor) or `--inkscape` (in Inkscape) |

## 7. Common problems

- **`rectification by the ArUco base failed`** — too few markers detected. Print `base.svg` on
  A4 at **100%**, shoot closer to the nadir with good light and no covered markers, and confirm
  `--dict` matches `make_calibration_target.py`.
- **Inflated/shifted outline** — parallax from the object's **height** (the top floats above
  the paper). No base corrects this; the tool only **measures and warns** about the tilt. Shoot
  as perpendicular as possible.
- **Light/matte part vanishes into the white** — it blends with the white center. With **two
  photos** (`--in2`, opposite light) the faint-metal predicate recovers it; in single-photo mode
  it remains a known limitation (see the roadmap in [docs/historico.md](docs/historico.md)).
- **`image not found`** — check the `--in` path.

## 8. Built-in help

```bash
.venv/Scripts/python photo_to_outline.py --help
.venv/Scripts/python make_calibration_target.py --help
```
