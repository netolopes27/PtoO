# PtoO — Photo to Outline

**English** · [Português](#ptoo--photo-to-outline-português)

Turns a **photo** of an object resting on the **printed calibration base** into an **SVG in
millimeters** holding the part's **outer outline** — perspective-corrected by the ArUco
markers, at **real scale**, and smoothed for 3D printing.

This README is the **usage guide** for the two CLIs (`make_calibration_target.py` and
`photo_to_outline.py`).

> For the project overview, internal pipeline, and roadmap, see [PROMPT.md](PROMPT.md).

---

## 1. Prerequisites (one time)

Requires **Python 3.14**. The vision deps (`numpy` + `opencv-python`) live **only** in an
isolated venv `./.venv/` — never install them globally.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Windows (PowerShell/Git Bash)
# .venv/bin/python -m pip install -r requirements.txt        # Linux/macOS
```

⚠️ **Always** run the tool and the tests with the venv's Python (`.venv/Scripts/python ...`),
not the system `python`.

To check everything is in place:

```bash
.venv/Scripts/python tests/run_image_tests.py     # expected: 50 tests, OK
```

---

## 2. The full flow in 4 steps

```
[1] generate base.svg  →  [2] print A4 100%  →  [3] photograph the part on the base  →  [4] photo_to_outline.py
```

1. **Generate the calibration base** (`make_calibration_target.py`) — guarantees that what
   you print is exactly what the detector expects.
2. **Print `base.svg` on A4 at 100%** (no "fit to page").
3. **Rest the part on the white center** and photograph it **from above, near the nadir**
   (use the gray guide ring: it only looks round on screen when the camera is perpendicular
   to the paper). See §2.1.
4. **Run `photo_to_outline.py`** on the photo → out comes the `.svg` in mm + a check overlay.

### 2.1 How to take the photo (reference recipe)

The sample photo (`thermpro.jpg`) was taken like this — follow the same recipe for
consistent results:

1. **With flash.** Strong, uniform lighting; it boosts the part's contrast against the paper
   and against the contact shadow.
2. **From far away, at the camera's highest resolution.** Shoot from **a good distance** and
   zoom in only afterwards (when cropping). A large distance makes the projection more
   **orthographic** — it reduces perspective and the parallax caused by the part's height.
   The maximum resolution leaves plenty of detail even after cropping.
3. **Perpendicular to the paper** (near the nadir), with the whole base and all markers
   visible.
4. **Then crop and frame the part** in the photo — crop the image so the part and the base
   are centered / fill the frame. The crop is free as long as the ArUco markers stay visible
   (the tool rescales by the base, not by the photo frame).

> In short: **flash + large distance + max resolution → crop and frame**. The large distance
> fights parallax; the high resolution survives the crop.

---

## 3. `make_calibration_target.py` — generate the base

```bash
.venv/Scripts/python make_calibration_target.py --out base.svg
```

Defaults: A4 landscape, 10 mm margin, 16 mm marker, dictionary `DICT_4X4_50` →
**32 markers**, white center **233×146 mm**.

| Flag | Default | What it does |
|------|---------|--------------|
| `--out` | `tools/base.svg` | path of the generated SVG (use `base.svg` at the root) |
| `--orientation` | `landscape` | `landscape` or `portrait` |
| `--page-margin` | `10.0` | margin from the page to the marker frame (mm) |
| `--marker-mm` | `16.0` | side of each ArUco marker (mm) |
| `--inner-pad` | `6.0` | gap between the frame and the white center (mm) |
| `--dict` | `DICT_4X4_50` | ArUco dictionary — **must match** the `--dict` of `photo_to_outline.py` |

> If you change `--dict` here, pass the **same** value when running `photo_to_outline.py`.

---

## 4. `photo_to_outline.py` — photo → SVG outline

### Minimal use

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg
```

Without `--out`, the SVG takes the photo's name (`thermpro.jpg` → `thermpro.svg`).

### Recommended use (default command) ⭐

This is the reference command — use it as your starting point:

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --max-nodes 300 --min-dist 0.5 --inkscape --symmetry vertical
```

What each flag does here: `--shadow remove` recovers the rounded edge; `--max-nodes 300`
+ `--min-dist 0.5` make the **pocket very tight** (many anchors, spaced just 0.5 mm apart);
`--symmetry vertical` reduces noise on a symmetric part; `--inkscape` also emits the
editable overlay. See §4.1 for the pocket detail.

Expected output for the sample photo **with this command**: measured object
**68.12 × 71.00 mm**, pocket (SVG) **67.69 × 70.93 mm** (clearance +0.43 × +0.07),
**300 Béziers** (smooth nodes), **contains the part 0.9982**. The fit comes out practically
flush with the part. For a **faithful** outline without the cap/quadrants use
`--max-nodes 0`; for a looser pocket lower the cap (`--max-nodes 8`, `12`…). See §4.1.

### Generated outputs

| File | When | What it is |
|------|------|------------|
| `<out>.svg` | always | the **outline in mm** (the deliverable) |
| `_overlay_<out>.png` | always | rectified photo + outline in red — **check it at a glance before accepting the SVG** |
| `_overlay_<out>.svg` | only with `--inkscape` | **editable** overlay: embedded photo (locked layer) + Béziers (editable layer), in the mm frame |

> The `_` prefix marks the overlays as drafts (git-ignored). Always look at the
> `_overlay_*.png` first: if the segmentation (red) is leaking or eating into the part,
> adjust the flags before using the `.svg`.

### 4.1 The fit POCKET mode (`--max-nodes`)

By default the script does **not** produce the most faithful outline possible — it produces
a **fit pocket**: the cavity where the part will rest (e.g. a recess in a 3D-printed case).
The priority is twofold: the part **fits** (the pocket is never smaller than it) and it sits
**snug** (tight). How it works:

1. **Quadrants.** It splits the part into `--max-nodes` equal angular sectors around the
   part's center (with `4`, one per quadrant).
2. **Extremities.** In each quadrant it anchors the **outermost tips** with **smooth-curve
   nodes**, and traces curves that **contain** the part (touching/cutting at most ~0.5 mm —
   `POCKET_EPS_MM` — so as not to inflate from sub-mm noise).
3. **Progression 4 → 8 → 12 → 16…** Each `+4` places **one more point per quadrant**,
   making the pocket **tighter**. Always multiples of 4.
4. **Spacing (`--min-dist`, default 10 mm).** The extra points within the **same quadrant**
   stay **≥ 10 mm** apart — the 1st anchor is the tip, the 2nd/3rd land ~10 mm further along,
   spread over the edges (without clustering at the tip). If the part is too small to fit the
   quota with that spacing, fewer points than the cap come out.
5. **Side protrusions (automatic, cap > 4).** Step 2 anchors the **corners** (whatever is
   most outward from the center), but a **bump in the middle of an edge** (rubber grip, side
   button) is not "outermost" — without an anchor there, the smooth curve would **round over**
   it. So, besides the quadrant anchors, the pocket **forces an anchor at each local
   protrusion**: a convex peak whose **prominence** (height above its neighborhood) exceeds
   `PROTRUSION_DEV_MM` (0.8 mm) gets its own node. They count **within the same cap** (the
   quadrant slots yield as needed, always keeping ≥ 4). Smooth/uniform curvature (a circle)
   does **not** trigger it — only a peak rising above the floor does. At cap `4` it doesn't
   act (the 4 slots belong to the corners).

| `--max-nodes` | points/quadrant | result (thermpro example) |
|---|---|---|
| `4` (default) | 1 | contains the part, still **loose** on the sides (~+5 mm) |
| `8` | 2 | **snug** (clearance ~+1.4 mm) |
| `12`, `16`, … | 3, 4, … | tighter and tighter |
| `0` | — | **faithful mode** (no cap/quadrants): truly tight outline, bbox = object |

> **Important:** in pocket mode the SVG comes out **close to the part's size** (the output
> reports the clearance, e.g. `pocket = 73.29 × 74.62 mm`). The curve may **lightly
> touch/cut** the part (up to `POCKET_EPS_MM`, ~0.5 mm) so it doesn't bloat from sub-mm
> noise — the actual fit is guaranteed by the print clearance you apply afterwards (see
> `--clearance`). If you need the part's **exact** outline (bbox = measured size), use
> `--max-nodes 0`.

### Flags

**Input/output**

| Flag | Default | What it does |
|------|---------|--------------|
| `--in` / `-i` | **(required)** | input photo |
| `--out` / `-o` | `<in>.svg` | output SVG (mm) |
| `--name` | file name | label used in the SVG/overlay |
| `--dict` | `DICT_4X4_50` | ArUco dictionary of the base; **must match** `base.svg` |
| `--debug-dir` | — | writes intermediate PNGs (rectified/mask) for diagnosis |

**Segmentation (cut quality)**

| Flag | Default | What it does |
|------|---------|--------------|
| `--shadow` | `off` | `remove` turns on the **edge hysteresis**: recovers the rounded edge that curves toward the base — the **black bevel at the top** and the **desaturated orange toe at the bottom** — growing only through pixels **with chroma** (the plastic) and **stopping at the gray contact shadow** of the base (which would leave the pocket loose) |
| `--symmetry` | `none` | `vertical` / `horizontal` / `both`: mirrors the mask and **averages the halves** (less noise). Use when the object is symmetric |

**Outline shape (nodes and smoothing)**

| Flag | Default | What it does |
|------|---------|--------------|
| `--smooth-mm` | `8.0` | low-pass window (mm) that removes the jaggies. Larger = smoother |
| `--simplify` | `2.0` | anchor density (mm): **larger = fewer nodes** (more "hull"); **smaller = tighter** (more nodes) |
| `--max-nodes` | `4` | **curve cap of the fit POCKET** (smooth Béziers), in steps of 4. Splits the part into **quadrants** and anchors the **extremity** of each sector; the curves **contain** the part. `4` = 1 point/quadrant (loose); `8`,`12`,`16`… = one more/quadrant (tighter). `0` = unlimited **faithful** mode (bbox = object). See §4.1 |
| `--min-dist` | `10` | **minimum distance (mm) between anchors of the same quadrant** in the pocket. Spaces the extra points (8, 12…) so they don't cluster at the tips. See §4.1 |
| `--min-radius` | `1.5` | minimum corner radius (mm); avoids 90° corners / spikes |
| `--guide` | (constant) | smoothing budget (mm): larger = **fewer** Béziers, looser cavity |

**Clearance / size**

| Flag | Default | What it does |
|------|---------|--------------|
| `--clearance` | `0` | external clearance (mm). **0 = REAL size**; apply the fit clearance downstream |
| `--c-fit` | `0.0` | clearance baked into the SVG (mm); 0 = minimal stroke touching the part |

**Output format**

| Flag | Default | What it does |
|------|---------|--------------|
| `--inkscape` | off | also emits the **editable SVG overlay** `_overlay_<out>.svg` for fine-tuning |
| `--polyline` | off | emits a raw polyline (`L`) instead of Bézier curves (`C`) |

**Advanced Bézier tuning** (rarely needed)

| Flag | Default | What it does |
|------|---------|--------------|
| `--tol-fit` | off | fits by **tolerance** (more nodes) instead of the containment minimum |
| `--fit-tol` | (constant) | fit tolerance (mm) — only takes effect with `--tol-fit` |

---

## 5. Checking in Inkscape (fine-tuning)

With `--inkscape`, open the `_overlay_<out>.svg`:

1. The rectified photo comes in a **locked layer**; the outline (Béziers, all with smooth G1
   nodes) in an **editable layer**, already in the mm frame.
2. Adjust the nodes over the photo where the segmentation got it wrong.
3. **Delete the photo layer** and export — the result is already at **real scale** (mm).

---

## 6. Quick recipes

| Situation | What to do |
|-----------|------------|
| Part with a **rounded edge** (black top or colored rim) whose edge disappears | `--shadow remove` |
| **Symmetric** part with a noisy outline | `--symmetry vertical` (or `horizontal`/`both`) |
| **Jagged** outline | increase `--smooth-mm` (e.g. `12`) |
| Pocket **too loose** (I want it snugger) | raise `--max-nodes`: `8`, `12`, `16`… (one more point/quadrant per step) |
| I want the part's **faithful outline** (bbox = object) | `--max-nodes 0` |
| **WARNING** "pocket does not contain the part" | raise `--max-nodes` (rare; only if the inflation wasn't enough) |
| I want to **diagnose** the segmentation | `--debug-dir debug/` and look at the PNGs |
| I want to **hand-edit** afterwards | `--inkscape` |

---

## 7. Common problems

- **`ERROR: rectification by the ArUco base failed`** — the base wasn't detected (too few
  markers). Print `base.svg` on A4 at **100%**, rest the part on the white center, and shoot
  closer to the nadir, with good light and no covered markers. Confirm that `--dict` matches
  the one used in `make_calibration_target.py`.
- **Inflated/shifted outline** — parallax from the object's **height** (the top floats above
  the paper). No base corrects this; the tool only **measures and warns** about the tilt.
  Shoot as perpendicular as possible.
- **Light/matte part vanishes into the white** — the object blends with the white center.
  Known limitation (see the roadmap in [PROMPT.md](PROMPT.md)); improve contrast/lighting.
- **`image not found`** — check the path passed to `--in`.

---

## 8. See the built-in help

Each CLI has `--help` with the texts kept up to date straight from the code:

```bash
.venv/Scripts/python photo_to_outline.py --help
.venv/Scripts/python make_calibration_target.py --help
```

---
---

# PtoO — Photo to Outline (Português)

[English](#ptoo--photo-to-outline) · **Português**

Converte a **foto** de um objeto apoiado na **base de calibração impressa** num **SVG em
milímetros** com o **contorno externo** da peça — corrigido de perspectiva pelos marcadores
ArUco, na **escala real** e suavizado para impressão 3D.

Este README é o **guia de uso** dos dois CLIs (`make_calibration_target.py` e
`photo_to_outline.py`).

> Para a visão geral do projeto, pipeline interno e roadmap, veja [PROMPT.md](PROMPT.md).

---

## 1. Pré-requisitos (uma vez)

Requer **Python 3.14**. As deps de visão (`numpy` + `opencv-python`) vivem **só** num venv
isolado `./.venv/` — nunca instale global.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Windows (PowerShell/Git Bash)
# .venv/bin/python -m pip install -r requirements.txt        # Linux/macOS
```

⚠️ **Sempre** rode a tool e os testes com o Python do venv (`.venv/Scripts/python ...`),
não com o `python` do sistema.

Para conferir que está tudo no lugar:

```bash
.venv/Scripts/python tests/run_image_tests.py     # esperado: 50 testes, OK
```

---

## 2. Fluxo completo em 4 passos

```
[1] gerar base.svg  →  [2] imprimir A4 100%  →  [3] fotografar a peça na base  →  [4] photo_to_outline.py
```

1. **Gere a base de calibração** (`make_calibration_target.py`) — garante que o que você
   imprime é exatamente o que o detector espera.
2. **Imprima `base.svg` em A4 a 100%** (sem "ajustar à página"/"fit to page").
3. **Apoie a peça no centro branco** e fotografe **de cima, perto do nadir** (use o anel-guia
   cinza: ele só fica redondo na tela quando a câmera está perpendicular ao papel). Ver §2.1.
4. **Rode `photo_to_outline.py`** sobre a foto → sai o `.svg` em mm + overlay de conferência.

### 2.1 Como fotografar (receita de referência)

A foto de exemplo (`thermpro.jpg`) foi tirada assim — siga a mesma receita para resultados
consistentes:

1. **Com flash.** Iluminação forte e uniforme; realça o contraste da peça contra o papel e
   contra a sombra de contato.
2. **De longe, na maior resolução da câmera.** Fotografe **a uma boa distância** e dê zoom só
   depois (no recorte). Distância grande deixa a projeção mais **ortográfica** — reduz a
   perspectiva e a paralaxe pela altura da peça. A resolução máxima garante detalhe de sobra
   mesmo depois de cortar.
3. **Perpendicular ao papel** (perto do nadir), com a base inteira e os marcadores visíveis.
4. **Depois, corte e enquadre a peça** na foto — recorte a imagem deixando a peça e a base
   centralizadas/preenchendo o quadro. O recorte é livre desde que os marcadores ArUco
   continuem visíveis (a tool reescala pela base, não pela moldura da foto).

> Resumo: **flash + distância grande + resolução máxima → cortar e enquadrar**. Distância
> grande combate a paralaxe; a resolução alta sobrevive ao corte.

---

## 3. `make_calibration_target.py` — gerar a base

```bash
.venv/Scripts/python make_calibration_target.py --out base.svg
```

Defaults: A4 paisagem, margem 10 mm, marcador 16 mm, dicionário `DICT_4X4_50` →
**32 marcadores**, miolo branco **233×146 mm**.

| Flag | Default | O que faz |
|------|---------|-----------|
| `--out` | `tools/base.svg` | caminho do SVG gerado (use `base.svg` na raiz) |
| `--orientation` | `landscape` | `landscape` ou `portrait` |
| `--page-margin` | `10.0` | margem da página até a moldura de marcadores (mm) |
| `--marker-mm` | `16.0` | lado de cada marcador ArUco (mm) |
| `--inner-pad` | `6.0` | folga entre a moldura e o miolo branco (mm) |
| `--dict` | `DICT_4X4_50` | dicionário ArUco — **tem que casar** com o `--dict` do `photo_to_outline.py` |

> Se mudar `--dict` aqui, passe o **mesmo** valor ao rodar `photo_to_outline.py`.

---

## 4. `photo_to_outline.py` — foto → contorno SVG

### Uso mínimo

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg
```

Sem `--out`, o SVG sai com o mesmo nome da foto (`thermpro.jpg` → `thermpro.svg`).

### Uso recomendado (comando default) ⭐

Este é o comando de referência — use-o como ponto de partida:

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --max-nodes 300 --min-dist 0.5 --inkscape --symmetry vertical
```

O que cada flag faz aqui: `--shadow remove` recupera a borda arredondada; `--max-nodes 300`
+ `--min-dist 0.5` deixam o **pocket bem justo** (muitas âncoras, espaçadas a só 0,5 mm);
`--symmetry vertical` reduz ruído numa peça simétrica; `--inkscape` gera também o overlay
editável. Ver §4.1 para o detalhe do pocket.

Saída esperada para a foto de exemplo **com esse comando**: objeto medido
**68,12 × 71,00 mm**, pocket (SVG) **67,69 × 70,93 mm** (folga +0,43 × +0,07),
**300 Béziers** (nós suaves), **contém a peça 0,9982**. O encaixe sai praticamente colado à
peça. Para um contorno **fiel** sem o teto/quadrantes use `--max-nodes 0`; para um pocket
mais folgado baixe o teto (`--max-nodes 8`, `12`…). Ver §4.1.

### Saídas geradas

| Arquivo | Quando | O que é |
|---------|--------|---------|
| `<out>.svg` | sempre | o **contorno em mm** (entregável) |
| `_overlay_<out>.png` | sempre | foto retificada + contorno em vermelho — **confira de relance antes de aceitar o SVG** |
| `_overlay_<out>.svg` | só com `--inkscape` | overlay **editável**: foto embutida (camada travada) + Béziers (camada editável), no referencial mm |

> O prefixo `_` marca os overlays como rascunho (ignorados pelo git). Sempre olhe o
> `_overlay_*.png` primeiro: se a segmentação (vermelho) estiver vazando ou comendo a peça,
> ajuste as flags antes de usar o `.svg`.

### 4.1 O modo POCKET de encaixe (`--max-nodes`)

Por padrão o script **não** gera o contorno mais fiel possível — gera um **pocket de
encaixe**: a cavidade onde a peça vai descansar (ex. um recorte num case impresso em 3D).
A prioridade é dupla: a peça **cabe** (o pocket nunca é menor que ela) e fica **firme**
(justo). Como funciona:

1. **Quadrantes.** Divide a peça em `--max-nodes` setores angulares iguais em torno do
   meio da peça (com `4`, um por quadrante).
2. **Extremidades.** Em cada quadrante ancora as **pontas mais externas** com **nós de
   curva suave**, e traça curvas que **contêm** a peça (toca/corta no máximo ~0,5 mm —
   `POCKET_EPS_MM` — para não inflar por ruído sub-mm).
3. **Progressão 4 → 8 → 12 → 16…** Cada `+4` coloca **mais um ponto por quadrante**,
   deixando o pocket **mais justo**. Sempre múltiplos de 4.
4. **Espaçamento (`--min-dist`, default 10 mm).** Os pontos extras de um **mesmo
   quadrante** ficam a **≥ 10 mm** um do outro — a 1ª âncora é a ponta, a 2ª/3ª caem
   ~10 mm adiante, espalhadas pelas bordas (sem aglomerar na ponta). Se a peça for pequena
   demais para caber a cota com esse espaçamento, saem menos pontos que o teto.
5. **Saliências laterais (automático, teto > 4).** O passo 2 ancora os **cantos** (o que é
   mais externo ao centro), mas um **ressalto no meio de uma aresta** (pega de borracha,
   botão lateral) não é "externo" — sem âncora ali, a curva suave **arredondaria por cima**
   dele. Então, além das âncoras de quadrante, o pocket **força uma âncora em cada saliência
   local**: um pico convexo cuja **proeminência** (altura acima da vizinhança) passe de
   `PROTRUSION_DEV_MM` (0,8 mm) ganha nó próprio. Entram **dentro do mesmo teto** (as vagas
   de quadrante cedem o necessário, sempre mantendo ≥ 4). Curvatura suave/uniforme (um
   círculo) **não** dispara — só o pico se ergue acima do fundo. No teto `4` não age (as 4
   vagas são dos cantos).

| `--max-nodes` | pontos/quadrante | resultado (exemplo thermpro) |
|---|---|---|
| `4` (default) | 1 | contém a peça, ainda **folga** nas laterais (~+5 mm) |
| `8` | 2 | **justo** (folga ~+1,4 mm) |
| `12`, `16`, … | 3, 4, … | cada vez mais firme |
| `0` | — | **modo fiel** (sem teto/quadrantes): contorno justo de verdade, bbox = objeto |

> **Importante:** no modo pocket o SVG fica **próximo do tamanho da peça** (a saída reporta
> a folga, ex. `pocket = 73,29 × 74,62 mm`). A curva pode **tocar/cortar de leve** a peça
> (até `POCKET_EPS_MM`, ~0,5 mm) para não estufar por ruído sub-mm — o encaixe real é
> garantido pela folga de impressão que você aplica depois (ver `--clearance`). Se precisa
> do contorno **exato** da peça (bbox = dimensão medida), use `--max-nodes 0`.

### Flags

**Entrada/saída**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--in` / `-i` | **(obrigatório)** | foto de entrada |
| `--out` / `-o` | `<in>.svg` | SVG de saída (mm) |
| `--name` | nome do arquivo | rótulo usado no SVG/overlay |
| `--dict` | `DICT_4X4_50` | dicionário ArUco da base; **deve casar** com `base.svg` |
| `--debug-dir` | — | grava PNGs intermediários (retificada/máscara) p/ diagnóstico |

**Segmentação (qualidade do recorte)**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--shadow` | `off` | `remove` liga a **histerese de borda**: recupera a borda arredondada que vira p/ a base — o **bisel preto no topo** e o **toe laranja dessaturado no fundo** — crescendo só pelos pixels **com croma** (o plástico) e **parando na sombra de contato cinza** da base (que deixaria o pocket frouxo) |
| `--symmetry` | `none` | `vertical` / `horizontal` / `both`: espelha a máscara e faz a **média das metades** (menos ruído). Use quando o objeto é simétrico |

**Forma do contorno (nós e suavização)**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--smooth-mm` | `8.0` | janela do low-pass (mm) que tira o serrilhado. Maior = mais liso |
| `--simplify` | `2.0` | densidade das âncoras (mm): **maior = menos nós** (mais "hull"); **menor = mais justo** (mais nós) |
| `--max-nodes` | `4` | **teto de curvas do POCKET de encaixe** (Béziers suaves), em passos de 4. Divide a peça em **quadrantes** e ancora a **extremidade** de cada setor; as curvas **contêm** a peça. `4` = 1 ponto/quadrante (folgado); `8`,`12`,`16`… = mais 1/quadrante (mais justo). `0` = modo **fiel** ilimitado (bbox = objeto). Ver §4.1 |
| `--min-dist` | `10` | distância **mínima (mm) entre âncoras do mesmo quadrante** no pocket. Espaça os pontos extras (8, 12…) para não aglomerar nas pontas. Ver §4.1 |
| `--min-radius` | `1.5` | raio mínimo de canto (mm); evita cantos de 90° / bicos |
| `--guide` | (constante) | orçamento de suavização (mm): maior = **menos** Béziers, cavidade mais folgada |

**Folga / dimensão**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--clearance` | `0` | folga externa (mm). **0 = tamanho REAL**; aplique a folga de encaixe a jusante |
| `--c-fit` | `0.0` | folga embutida no SVG (mm); 0 = traço mínimo encostando na peça |

**Formato de saída**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--inkscape` | off | gera também o **overlay SVG editável** `_overlay_<out>.svg` p/ ajuste fino |
| `--polyline` | off | emite polilinha crua (`L`) em vez de curvas de Bézier (`C`) |

**Ajuste avançado de Bézier** (raramente preciso)

| Flag | Default | O que faz |
|------|---------|-----------|
| `--tol-fit` | off | ajusta por **tolerância** (mais nós) em vez do mínimo por contenção |
| `--fit-tol` | (constante) | tolerância (mm) do ajuste — só tem efeito com `--tol-fit` |

---

## 5. Conferindo no Inkscape (ajuste fino)

Com `--inkscape`, abra o `_overlay_<out>.svg`:

1. A foto retificada vem numa **camada travada**; o contorno (Béziers, todos com nós
   suaves G1) numa **camada editável**, já no referencial mm.
2. Ajuste os nós sobre a foto onde a segmentação errou.
3. **Apague a camada da foto** e exporte — o resultado já está na **escala real** (mm).

---

## 6. Receitas rápidas

| Situação | O que fazer |
|----------|-------------|
| Peça com **borda arredondada** (topo preto ou rim colorido) cuja borda some | `--shadow remove` |
| Peça **simétrica** e contorno ruidoso | `--symmetry vertical` (ou `horizontal`/`both`) |
| Contorno **serrilhado** | aumente `--smooth-mm` (ex. `12`) |
| Pocket **folgado demais** (quero mais firme) | suba `--max-nodes`: `8`, `12`, `16`… (mais 1 ponto/quadrante por passo) |
| Quero o **contorno fiel** da peça (bbox = objeto) | `--max-nodes 0` |
| **AVISO** "pocket não contém a peça" | suba `--max-nodes` (raro; só se a estufa não bastou) |
| Quero **diagnosticar** a segmentação | `--debug-dir debug/` e olhe as PNGs |
| Quero **editar à mão** depois | `--inkscape` |

---

## 7. Problemas comuns

- **`ERRO: retificação pela base ArUco falhou`** — a base não foi detectada (poucos
  marcadores). Imprima `base.svg` em A4 a **100%**, apoie a peça no centro branco e
  fotografe mais perto do nadir, com boa luz e sem marcadores cobertos. Confirme que o
  `--dict` casa com o usado em `make_calibration_target.py`.
- **Contorno inflado/deslocado** — paralaxe pela **altura** do objeto (o topo flutua sobre
  o papel). Nenhuma base corrige; a tool só **mede e avisa** a inclinação. Fotografe o mais
  perpendicular possível.
- **Peça clara/fosca some no branco** — o objeto se confunde com o miolo branco. Limitação
  conhecida (ver roadmap no [PROMPT.md](PROMPT.md)); melhore o contraste/iluminação.
- **`imagem não encontrada`** — confira o caminho passado em `--in`.

---

## 8. Ver a ajuda embutida

Cada CLI tem `--help` com os textos atualizados direto do código:

```bash
.venv/Scripts/python photo_to_outline.py --help
.venv/Scripts/python make_calibration_target.py --help
```
