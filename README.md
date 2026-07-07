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
.venv/Scripts/python tests/run_image_tests.py     # expected: OK (all tests green)
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
| `--out` | `base.svg` | path of the generated SVG |
| `--orientation` | `landscape` | `landscape` or `portrait` |
| `--page-margin` | `10.0` | margin from page to marker frame (mm) |
| `--marker-mm` | `16.0` | side of each ArUco marker (mm) |
| `--inner-pad` | `6.0` | gap between frame and white center (mm) |
| `--dict` | `DICT_4X4_50` | ArUco dictionary — **must match** `photo_to_outline.py`'s `--dict` |

## 4. `photo_to_outline.py` — photo → SVG outline

Minimal: `photo_to_outline.py --in thermpro.jpg` (SVG takes the photo's name).

> **Where files live.** Keep the photos of your own mapped items in the **`images/`** folder so the
> repo root stays clean as the map grows. The tool writes the `.svg` (and the `_overlay_*` drafts)
> **next to the input photo**, so `--in images/foo.jpg` produces `images/foo.svg` with no explicit
> `--out`. The bundled sample `thermpro.jpg` and the printable `base.svg` stay in the root.

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
(pocket never smaller) and sits **snug**. It anchors the outermost points of the part (plus every
local protrusion, so a grip or side button isn't rounded over) and traces smooth curves that
**contain** the part; straight stretches and corner fillets are emitted as **exact lines and
tangent arcs** (v0.10, on by default), so a straight edge never bows inward.

**`--min-dist` is the one tightness lever** — there is no node cap; the anchor count emerges
purely from the spacing. Lower it (e.g. `1`, `0.6`) until "contains the part" crosses your
target; stop at the **largest** value that still crosses (fewer nodes is better).

| `--min-dist` | result (thermpro) |
|---|---|
| `10` (default) | contains the part, **loose** on the sides |
| `1` | snug (~201 Béziers, contains 0.9998) |
| `0.6` | flush (305 Béziers, **contains 0.9999**) |
| `--faithful` | **faithful mode**: tight outline, bbox = object |

> **Counter-intuitive:** a **large** `--min-dist` (few anchors) makes the pocket **both looser
> and less contained** — sparse anchors give long Béziers that bow **inward** at rounded corners,
> cutting the part. To contain more, **lower** `--min-dist`.
>
> In pocket mode the SVG comes out **close to the part's size** (the output reports the
> clearance). The real fit is guaranteed by the print clearance you apply downstream (see
> `--clearance`). For the part's **exact** outline (bbox = measured size), use `--faithful`.

Full mechanism (quadrants, protrusion anchors, geometric primitives, containment floor):
[docs/design.md](docs/design.md) §Pipeline (pt-BR).

### Flags (summary)

The **authoritative per-flag reference** — defaults, when to change each one, interactions and
their effect on containment — is [docs/manual.md](docs/manual.md) (pt-BR). Quick map:

| Flag | Default | One-liner |
|------|---------|-----------|
| `--in/-i` · `--out/-o` · `--name` | — | input photo (required) · output SVG (`<in>.svg`) · label |
| `--dict` | `DICT_4X4_50` | ArUco dictionary — **must match** the printed `base.svg` |
| `--shadow` | `off` | `remove` = chroma edge hysteresis (chromatic parts); `texture` = texture shadow subtractor + watershed edge refine (gray-neutral bodies) |
| `--val-frac` | `0.30` | dark-pixel cut; raise (~0.7) for low-contrast gray bodies |
| `--in2` | off | two-photo fusion with opposite light: kills hard shadows, recovers bright metal |
| `--fuse-grow` | `0.0` | optional geodesic grow after fusion (rarely needed) |
| `--symmetry` | `none` | mirror the mask and average the halves (`vertical`/`horizontal`/`both`) |
| `--level` | `off` | `auto` = fix the fine rotation (0.2–7°) of a part laid slightly askew |
| `--humble` | `auto` | straight chords where the edge has no visual support; leftovers flagged in orange |
| `--mask-smooth-mm` | `0.0` | regularize the silhouette itself (wavy low-contrast black edge) |
| `--mask-smooth-keep-bumps` | off | bias regularization to keep convex bumps (side tabs) |
| `--min-dist` | `10` | **pocket tightness lever**: smaller = more anchors = tighter (§4.1) |
| `--line-tol` / `--arc-tol` | `0.3` | exact straight lines / tangent arcs; `--line-tol 0` disables both |
| `--corner-radius` | `0` | declared corner radius (caliper-measured): detected corner arcs snap to it |
| `--shape` | `off` | `rect` = part declared a rounded rectangle: pocket **built** exactly (4 lines + 4 arcs, 8 Béziers); falls back with a warning if the silhouette disagrees |
| `--smooth-mm` | `8.0` | low-pass window; fine containment lever (lower toward `2`) |
| `--pocket-eps` | `0.5` | tolerated penetration in pocket mode (fine-tuning only) |
| `--min-radius` | `1.5` | minimum corner radius (no 90° corners / spikes) |
| `--faithful` | off | faithful outline (bbox = object) instead of the fit pocket |
| `--simplify` | `2.0` | anchor density in faithful mode |
| `--clearance` / `--c-fit` | `0.0` | clearance baked into the SVG — normally applied downstream instead |
| `--inkscape` | off | also emit the editable SVG overlay (§5b) |
| `--edit` | off | open the built-in node editor before saving (§5) |
| `--polyline` | off | raw `L` polyline instead of Bézier `C` curves |
| `--tol-fit` / `--fit-tol` / `--guide` | off | tolerance-based fit (rarely needed) |
| `--debug-dir` | off | dump intermediate stages for diagnosis |

## 5. Adjust nodes in the built-in editor (`--edit`)

Detection always errs a little (shadow/glare on the edge), so you usually want a manual touch-up.
With `--edit`, the tool detects as usual and then opens a small window (tkinter, no extra install):
the **rectified photo** as background and the curve's **nodes as draggable handles**.

- **Drag** a handle to move a node · **click on the curve** to insert a node · **right-click** a
  handle to delete it · mouse wheel = **zoom at the cursor**, **Ctrl + left-drag** = pan.
- **Re-trace** draws a smooth (G1) curve through your nodes (editing re-traces automatically);
  **Undo** / **Reset** as usual.
- Toolbar (one-liners; full operation in [docs/manual.md](docs/manual.md) §`--edit`, pt-BR):
  **Line** (Shift+click 2 nodes → exact straight segment) · **Symmetry** (edits mirrored across a
  draggable axis) · **Mirror ◀/▶** (rebuild one side as the mirror of the other) · **Size**
  (live green W×H dimension) · **Rotate** (fine rotation of photo+nodes, 0.1° steps) ·
  **Pan** (fine sideways nudge of the outline, 0.1 mm steps) · **Measure** (point-to-point mm
  measurements, axis-locked — Ctrl = free angle; they persist highlighted until right-clicked).
- **Finalize** is **WYSIWYG**: it closes the window and writes the same outputs from **exactly the
  curve on screen** — nothing is recomputed (closing the window without Finalize writes nothing).

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
/ptoo <photo.jpg> --pass N [--debug] [--describe "text"]
```

- `<photo.jpg>` — the input photo (a bare name resolves at the repo root).
- `--pass N` — hard cap on calibration attempts (default 3).
- `--debug` — after converging, also emit a CLI-improvement package (diagnosis + proposed
  diff + a next-version plan under `docs/melhorias/`); does **not** touch the CLI.
- `--describe "text"` — natural-language description of what you **know** about the part
  ("a rectangle with 3 mm rounded corners"); the skill turns it into geometry priors for the
  CLI (`--shape rect`, `--corner-radius`) before the loop starts.

It calibrates toward *contains the part* ≥ **0.9999** with the fewest nodes, keeps a small
memory of good parameters per part, and finishes with one optional `--edit` pass. Full behavior
(levers, heuristics, memory) is documented in the skill's own
[SKILL.md](.claude/skills/ptoo/SKILL.md) — the single source for the procedure.

> The skill is Claude-Code-only and is invoked by typing `/ptoo …` in a Claude Code session; it
> is not a shell command. Under the hood it just calls the same `photo_to_outline.py` you can run
> by hand (§4).

## 6. Quick recipes

| Situation | What to do |
|-----------|------------|
| **Rounded edge** (black top / colored rim) disappearing | `--shadow remove` |
| **Hard sunlight shadow** no `--shadow` mode fixes | second photo with opposite light + `--in2 photo2.jpg` |
| **Bright metal connector** vanishing into the white paper | same: `--in2` (auto-recovers faint metal) |
| **Light part ≈ white paper** — edge with no contrast almost everywhere (CLI warns `só NN% da borda tem apoio visual`) | `--humble` already activated by itself: check the **orange flagged stretches** in the overlay, touch up in `--edit` if needed |
| **Symmetric** part, noisy outline | `--symmetry vertical` (or `horizontal`/`both`) |
| Part laid **slightly askew** on the base (~0.5–5°) | `--level auto` (or the editor's **Rotate** mode) |
| Shadow **inflated one side** of a symmetric part | `--edit` → Symmetry on → drag the axis → **Mirror** with the good side |
| **Jagged** outline | raise `--smooth-mm` (e.g. `12`) |
| Pocket **too loose** | lower `--min-dist`: `2`, `1`, `0.5`… |
| You **measured** the part (it *is* a rounded rectangle, radius R) | `--shape rect --corner-radius R` — the pocket is built exactly (8 Béziers) |
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
