# Design — arquitetura e API do PtoO

Foto sobre a base ArUco → SVG do contorno em mm. Guia de uso: [README.md](../README.md);
evolução e roadmap: [historico.md](historico.md).

## O quê

Front-end **fotográfico** de uma cadeia *item holder* gridfinity: dada uma **foto** de um
objeto sobre a **base de calibração impressa** (moldura ArUco + miolo branco, `base.svg`),
o PtoO produz um **SVG em mm** (contorno + preenchimento translúcido) com o **contorno externo**
da peça, corrigido de perspectiva/inclinação pelos marcadores, em **mm verdadeiros** e suavizado
para impressão 3D. **Objetivo:** a cavidade (pocket) onde a peça encaixa num case impresso. O
fluxo **termina no SVG**; levar para OpenSCAD é trabalho de um exportador externo.

Ferramenta **Python de visão autocontida**: roda num **venv** (`./.venv/`) com `numpy` +
`opencv-python`, resto stdlib. Código em inglês, esta doc em pt-BR, unidades em mm. O contorno
sai **direto do JPG** (escala pelos marcadores) — sem referência desenhada à mão.

**Arquivos:** `photo_to_outline.py` (a tool) · `calibration_target.py` (layout puro) ·
`make_calibration_target.py` (gera `base.svg`) · `outline_editor.py` (editor de nós opcional,
`--edit`) · `base.svg` · `requirements.txt` · `./.venv/`.
**Testes:** `tests/test_photo_to_outline.py` + `tests/test_calibration_target.py` (runner
`tests/run_image_tests.py`). **E/S:** `thermpro.jpg` → `thermpro.svg`.

## Base de calibração — "moldura ArUco + centro branco"

Moldura de marcadores **ArUco** ao redor de uma folha **A4** com **miolo branco liso** onde o
objeto é apoiado. Escolhida (vs uma grade de quadrados) porque cada marcador tem **ID único**
(sem ambiguidade de orientação, robusto a oclusão), cantos **sub-pixel** (homografia precisa,
`cv2.aruco` nativo, sem dep nova) e, sobretudo, **segmentação trivial**: objeto sobre branco,
**sem nenhuma linha** para confundir com a borda preta da peça. O tool **gera a própria base**,
garantindo que *o impresso == o que o detector assume*. Validado em `thermpro.jpg`: 32/32
marcadores, lado reprojetado 15,87 mm (alvo 16), inclinação ~1°. Um **anel-guia** cinza-claro
(círculo + cruz) no miolo só fica redondo na tela quando a câmera está no nadir (sob inclinação
vira elipse, `cos θ = eixo_menor/eixo_maior`); o cinza fica acima do limiar de segmentação, não
polui o contorno.

- **`calibration_target.py` (PURO — fonte única do layout):** `target_layout(page, page_margin,
  marker_mm, inner_pad, min_gap, dict_name)` → dict com `page`, `marker_mm`, `dict`, `capacity`,
  `modules`, `inner_rect` (retângulo branco) e `markers` (`Marker(id,x,y,size)`, IDs
  sequenciais, moldura de uma espessura). `Marker.corners_mm()` → 4 cantos na **ordem ArUco**
  (tl, tr, br, bl; Y p/ baixo). `homography_correspondences(layout)` → `[(id, [4 cantos mm])]`
  = **contrato consumido por `photo_to_outline.aruco_correspondences`**. `A4_LANDSCAPE`/
  `A4_PORTRAIT`, `DICT_CAPACITY`/`DICT_MODULES`. Defaults: A4 paisagem, margem 10 mm, marcador
  16 mm, `inner_pad` 6, `DICT_4X4_50` → 32 marcadores, miolo 233×146 mm.
- **`make_calibration_target.py` (renderiza o SVG):** marcadores como retângulos pretos
  vetoriais (run-length por linha de módulos, `cv2.aruco.generateImageMarker` a 1 px/módulo),
  fundo branco com margem, anel-guia e instrução de impressão a 100%. CLI: `--out`,
  `--orientation`, `--page-margin`, `--marker-mm`, `--inner-pad`, `--dict`. Aborta se nº de
  marcadores > capacidade do dicionário.

> ⚠️ Limite físico que **nenhuma** base corrige: o objeto tem altura → o topo flutua sobre o
> papel (paralaxe), inflando/deslocando o contorno. Mitigado só fotografando perto do nadir.

## Pipeline (5 estágios)

1. **Detectar a moldura ArUco + RETIFICAR por HOMOGRAFIA (1º passo — sai a dimensão real).**
   `detect_markers` (`cv2.aruco.detectMarkers`, cantos sub-pixel); cada ID casa com seus 4
   cantos nominais em mm via `homography_correspondences` (`aruco_correspondences`);
   `findHomography(RANSAC)` resolve **imagem→mm** sobre todos os cantos (sobredeterminada →
   robusta). `rectify` **recorta o MIOLO BRANCO** num canvas de escala **UNIFORME** `PX_PER_MM`
   (compõe mm→px ∘ imagem→mm + `warpPerspective`, `borderValue` branco) — marcadores e anel-guia
   ficam fora → o segmentador vê só objeto sobre branco. `estimate_tilt_deg` estima a
   **inclinação** vs o nadir (decompõe a pose com intrínseca aproximada) e **avisa** acima de
   `TILT_WARN_DEG`. Devolve `(rectified, mm_per_px, mm_per_px, conf)`; `< MIN_MARKERS` →
   `GridDetectionError`.
2. **Normalizar luz + segmentar (objeto sobre branco).** `normalize_illumination` (flat-field):
   a sombra difusa é um escurecimento suave e multiplicativo do branco; estima o campo de luz
   `L(x,y)` por **closing em escala-cinza** (kernel > objeto) + borrão em escala reduzida
   (`ILLUM_SCALE`) e **divide** a imagem por `L` (hue-preserving, teto `ILLUM_MAX_GAIN`). Depois
   `segment_tool`: o fundo é o miolo branco; a **moldura da borda** do canvas é fundo puro →
   amostrada (mediana HSV) p/ modelar o branco (**auto-adapta** à luz/balanço). Pixel = objeto
   se **colorido** (saturação ≥ fundo + `SEG_SAT_MARGIN`) **OU cromático** (matiz distante,
   `SEG_HUE_MARGIN`/`SEG_HUE_SAT_MIN`) **OU escuro** (brilho ≤ `SEG_VAL_FRAC`×fundo); a sombra
   suave é dessaturada e só um pouco escura → fica no fundo. Morfologia `open`/`close`, maior
   componente conectado, preenche buracos internos (display) → contorno cheio.
   **Estratégia de sombra (`--shadow`, opcional).** Dois modos, p/ dois regimes de sombra:
   - **`remove` — histerese por CROMA** (peça cromática). O corte único de escuro corta *dentro*
     da rampa preto→sombra→papel, comendo/serrilhando a borda arredondada que vira p/ a base (o
     **bisel preto no topo** e o **toe laranja dessaturado no fundo**). A histerese (estilo Canny)
     cresce os **núcleos certos** (preto E colorido) pelos pixels escuros vizinhos **com croma**
     (`V ≤ SEG_VAL_WEAK_FRAC×fundo` **e** `S ≥ SEG_WEAK_SAT_MIN`) por **dilatação geodésica de
     alcance limitado** (`SEG_SHADOW_GROW_MM`) até o papel claro. O **piso de saturação** separa a
     rampa cromática do plástico da **sombra de contato CINZA** (barrada).
   - **`texture` — subtrator por TEXTURA** (corpo CINZA-NEUTRO sem croma, com sombra projetada). O
     valor pega o corpo escuro inteiro (inclusive o liso) e a **textura** (std local de V numa
     janela `SEG_TEX_WIN`, limiar **Otsu adaptativo** da própria foto) **recorta** as regiões
     **lisas E mais claras** (`tex < Otsu` **e** `V > SEG_TEX_LIGHT_FRAC×fundo`) = a sombra
     projetada. O recorte vale p/ **todo** o candidato (valor **ou** croma), então a sombra não
     volta pela porta do cromático em fundo de papel saturado. Sombra de contato (escura) fica fora
     do termo de recorte (pendência). Padrão `off`.
2b. **Simetria (opcional, `--symmetry`).** `symmetrize_mask`: num objeto simétrico as duas
   metades são **duas medições do mesmo contorno** → espelhar e fazer a **média** cancela o
   ruído assimétrico e força a simetria. Acha o eixo pelo **centroide**, refina por **máx. IoU**
   (±`SYM_SEARCH_MM`) e faz a média pelo **campo de distância COM SINAL** (`_signed_distance`:
   >0 dentro, <0 fora; média morfológica, não AND/OR). `vertical`/`horizontal`/`both`. Padrão
   `none`.
3. **Contorno externo (`extract_outline`).** `findContours(RETR_EXTERNAL)` → maior área; px→mm
   com escala **por eixo** (`mm_per_px_x`, `mm_per_px_y`); inverte Y. A bbox = **dimensão real
   medida**.
4. **Suavizar p/ impressão (`process_for_print`).** `enforce_min_radius` (filete morfológico:
   nenhum canto convexo abaixo de `--min-radius`; + dilatação `--clearance`) → **low-pass forte**
   `lowpass_closed(--smooth-mm)` (remove serrilhado de alta freq., preserva features ≫ smooth-mm)
   → decimação `approxPolyDP`. Fechado, CCW, sem auto-interseção. **Sem ganho:** default
   `--clearance 0` → tamanho REAL; a folga é aplicada **a jusante**.
5. **Ajustar curvas + emitir SVG (`polygon_to_svg`).** Só **Béziers cúbicas**, poucos nós,
   contendo a peça. **Modo padrão — POCKET por quadrante** (`fit_closed_beziers_anchored`, default
   `faithful=False`): divide a peça em 4 quadrantes em torno do meio da bbox e ancora, em cada um,
   **todos** os pontos **mais externos** das pontas p/ dentro, com âncoras do **mesmo quadrante a
   ≥ `--min-dist` mm** (`_quadrant_anchors`) — **sem teto**: a densidade emerge só do espaçamento
   (menor `--min-dist` = mais âncoras = mais justo). Além disso **força uma âncora em cada
   saliência local** (`_protrusion_anchors`): pico convexo no meio de uma aresta (pega/botão) com
   **proeminência ≥ `PROTRUSION_DEV_MM`** que o seletor radial ignoraria. Entre âncoras, **1
   cúbica suave por trecho** que **contém** a peça: ajuste por mínimos quadrados que **estufa p/
   fora** (alonga handles, preservando G1) só se penetrar além de `POCKET_EPS_MM` (default,
   sobrescrito por `--pocket-eps`) (`_one_cubic_contained`). **Sem snap de bbox** — o pocket fica
   no tamanho real, ~objeto (mais âncoras = mais justo); avisa se a cobertura cair abaixo de
   `CONTAIN_COVERAGE`.
   **Lever da contenção = `--min-dist`** (alavanca principal de densidade): menor `--min-dist` =
   mais âncoras = pocket mais justo e `contém` mais alto; pare no MAIOR `--min-dist` que cruza o
   alvo. **Lever fino = `--smooth-mm`:** o piso de contenção (`field`) é construído sobre a
   silhueta **suavizada** (`clean`), enquanto a cobertura é medida contra a silhueta crua; logo
   suavizar demais deixa a peça crua vazar por fora → `contém` cai. Baixar `--smooth-mm` (8→2)
   aproxima o piso da peça e raspa o último 0.0x (≲1 reintroduz serrilhado). `--pocket-eps`
   (0.5→0) tem efeito sub-0.001 — ajuste fino, não o lever.
   **Modo fiel (`--faithful`):** ancora nos pontos mais distantes (fecho convexo destilado por
   RDP `--simplify`), ajusta cúbicas **contidas** entre âncoras (maior tolerância sem penetrar
   além de `ANCHOR_EPS_MM`, via `distanceTransform`) e **fixa a bbox (snap, por eixo) na dimensão
   real** (`_scale_cubics_to_bbox`).
   **Todo nó é SUAVE (G1)** nos dois modos: a tangente em cada âncora é **compartilhada** entre
   os trechos vizinhos (`_anchor_tangents`) → sem bico, fácil de editar no Inkscape. Saída =
   contorno + preenchimento translúcido (`OUTLINE_COLOR` a `OUTLINE_FILL_OPACITY`, sobrepõe o
   objeto p/ conferir cobertura). **Alternativos:** `--tol-fit`
   (`fit_closed_beziers_contained`); `--polyline` (`L` cru). Folga somada **a jusante** (escalar
   o SVG, `--c-fit`, ou `clearance` no OpenSCAD).

## API — funções puras (testáveis sem imagem)

**Geometria de polígono** (`pts` = `list[(x,y)]`/`ndarray Nx2`, em mm):
- `polygon_area`/`signed_area`/`ensure_ccw` (shoelace, winding); `is_closed`/`close_polygon`/
  `dedup_closing_point`; `bbox`/`size`.
- `douglas_peucker(pts, eps)` / `douglas_peucker_idx` (RDP, com índices);
  `chaikin(pts, iterations, closed)`; `lowpass_closed(pts, win_mm, step)` (Hann circular de
  x(s)/y(s)); `resample_uniform`.
- `corner_angles`; `corner_radii`; `min_corner_radius(pts, window=0.8)` (circunraio com vizinhos
  afastados ~`window` mm, sem o viés do estimador de 3 vizinhos imediatos);
  `enforce_min_radius(pts, r_min, clearance=0, closed)` (abertura+fechamento morfológico + dilata
  clearance).
- `boundary_roughness(pts, win_mm=2.0)` (aspereza vs low-pass); `coverage(outer, inner)` (fração
  de `inner` contida em `outer`; 1.0 = a peça cabe).
- **Ajuste de Bézier (Schneider):** `fit_closed_beziers(poly, tol, corner_angle)` → cúbicas
  `(p0,c1,c2,p3)`; `bezier_point`, `flatten_beziers`, `_corner_indices` (cusps, NMS circular),
  `_fit_one_cubic` (mínimos quadrados, tangentes fixas), `_fit_cubic_recursive` (split no maior
  erro).
- **Pocket ancorado (modo padrão):** `fit_closed_beziers_anchored(silhouette, smooth_mm,
  simplify_mm, eps, faithful=False, min_dist_mm)`; helpers `_quadrant_anchors`,
  `_protrusion_anchors`, `_fit_anchored`, `_one_cubic_contained` (estufa p/ conter, com
  **guarda de simplicidade**: handle ≤ `ANCHOR_HANDLE_CAP`·corda via `_cap_handles` e rejeição
  de candidatos que se auto-cruzam por `_cubic_is_simple`), `_anchor_tangents`
  (tangente compartilhada → nó G1), `_anchor_segments`. Modo fiel (`faithful=True`):
  `hull_anchor_indices` (fecho convexo via RDP) + `_fit_segment_contained`.
- **De-loop (contorno simples):** após montar/espelhar as cúbicas, `_repair_self_intersections`
  encurta (`_shrink_handles`) os handles das cúbicas que se cruzam — laço próprio ou com vizinha
  a ≤ janela de índice (`_self_intersecting_indices`, base `_segments_cross`) — até o caminho
  fechado ficar **sem auto-sobreposição** (dentro/fora bem definido p/ o boolean a jusante).
  Handle só encurta → a curva anda p/ dentro, mantendo a contenção.
- **Mínimo por contenção (`--tol-fit`):** `fit_closed_beziers_contained(guide, silhouette,
  c_fit, eps)`; `_floor_field` (profundidade via `distanceTransform`),
  `_max_penetration`/`_beziers_max_penetration`.
- **Snap:** `_scale_cubics_to_bbox(cubics, target_w, target_h)` (escala por eixo p/ a bbox =
  dimensão medida; modo fiel).

**Escala + retificação (homografia ArUco):** `px_per_mm`/`mm_per_px`;
`homography_from_corners`/`apply_homography`; `detect_markers(gray, dict_name)` →
`(corners, ids)`; `aruco_correspondences(corners, ids, layout)` → `(img_pts, mm_pts)`;
`estimate_tilt_deg(img_pts, mm_pts, shape)`. Layout/contrato vêm de `calibration_target.py`.

## API — pipeline (I/O)

`load_image(path)`; `rectify(img, dict_name)→(rectified, mm_per_px, mm_per_px, conf)`;
`normalize_illumination(img)→img`; `segment_tool(img, deshadow=False, val_frac)→mask`
(`deshadow` ∈ {False/"off", True/"remove", "texture"});
`symmetrize_mask(mask, axis, ppmm)→mask`; `extract_outline(mask, mm_per_px_x, mm_per_px_y)→pts`;
`process_for_print(...)→pts`; `polygon_to_svg(pts, name, …)→str`; `write_overlay(rect, mask,
path)` (PNG de conferência); `write_overlay_svg(rect, cubics, mm_per_px_x, mm_per_px_y, path)`
(SVG editável: foto embutida + Béziers); `generate_outline(..., overlay_path, overlay_svg_path)`.
Orquestrador `main(argv)`.

### CLI
```
python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    [--dict DICT_4X4_50] [--min-radius 1.5] [--smooth-mm 8] [--clearance 0] \
    [--shadow off|remove|texture] [--symmetry none|vertical|horizontal|both] [--inkscape] \
    [--simplify 2.0] [--min-dist 10] [--faithful] [--mask-smooth-mm 0] [--mask-smooth-keep-bumps] \
    [--tol-fit --fit-tol 0.2 --guide 0.5 --c-fit 0] [--polyline] [--edit] \
    [--name thermpro] [--debug-dir _debug]
```
Imprima `base.svg` em A4 a 100%, apoie a peça no centro branco, fotografe perto do nadir.
`--dict` deve casar com a base impressa. `--min-dist` = densidade do pocket (menor = mais justo,
**sem teto de nós**); `--faithful` = modo fiel com snap (bbox = objeto); `--simplify` controla a
densidade no modo fiel. `--shadow remove` = histerese de borda por croma; `--shadow texture` =
subtrator de sombra por textura (corpo cinza-neutro, v0.5); `--symmetry` = espelho + média. **A cada
execução** sai, antes do `.svg`, o overlay PNG `_overlay_<nome>.png` (contorno em vermelho sobre
a foto retificada); `--inkscape` gera também `_overlay_<nome>.svg` editável. `--edit` abre o
**editor de nós** (GUI tkinter, `outline_editor.py`, rótulos em inglês) entre a detecção e a saída:
foto retificada de fundo + nós da curva como alças (rodinha = zoom no cursor, Ctrl+arrasto = pan; fundo
renderizado por recorte do viewport, custo independente do zoom); o usuário move/inclui/exclui nós.
"Re-trace" traça a curva G1 pelos nós (spline Catmull-Rom, `cubics_through_nodes`) — mover/inserir/
excluir um nó já re-traça. **WYSIWYG:** "Finalize" grava as mesmas saídas a partir de **EXATAMENTE a
curva que está na tela** (as cúbicas do último Re-trace; emitidas literal, sem recalcular nem snap).
`--debug-dir` grava intermediários. Marcadores insuficientes → aborta
com mensagem clara. (Guia de flags completo: [README.md](../README.md) §4.)

## Constantes (defaults, topo de `photo_to_outline.py`)

`PX_PER_MM = 8.0` (resolução do canvas) · `DICT_NAME = "DICT_4X4_50"` · `MIN_MARKERS = 8` ·
`TILT_WARN_DEG = 5.0` · `SEG_SAT_MARGIN = 45` / `SEG_VAL_FRAC = 0.30` (colorido OU escuro vs
fundo; default do `--val-frac`, suba p/ corpo cinza-neutro) · `SEG_VAL_WEAK_FRAC = 0.65` / `SEG_WEAK_SAT_MIN = 35` / `SEG_SHADOW_GROW_MM = 3.0`
(histerese do `--shadow remove`) · `SEG_TEX_WIN = 9` / `SEG_TEX_GAIN = 6.0` / `SEG_TEX_BG_FRAC = 0.93`
/ `SEG_TEX_BODY_FRAC = 0.80` / `SEG_TEX_LIGHT_FRAC = 0.70` (subtrator de sombra do `--shadow texture`:
janela da textura, Otsu adaptativo, corte de corpo, corte de sombra-clara) ·
`SEG_HUE_MARGIN = 25` / `SEG_HUE_SAT_MIN = 60` (matiz) ·
`ILLUM_SCALE = 0.125` / `ILLUM_KERNEL_FRAC = 0.9` / `ILLUM_MAX_GAIN = 3.0` (flat-field) ·
`SYM_SEARCH_MM = 4.0` · `MIN_RADIUS_MM = 1.5` · `SMOOTH_MM = 8.0` · `CLEARANCE_MM = 0.0` (sem
ganho) · `ANCHOR_SIMPLIFY_MM = 2.0` (modo fiel) · `ANCHOR_EPS_MM = 0.08` (fiel)
· `POCKET_EPS_MM = 0.5` (penetração tolerada) · `ANCHOR_HANDLE_CAP = 0.40` (teto do handle =
fração da corda, anti-laço) · `ANCHOR_MIN_DIST_MM = 10.0` (densidade do pocket) ·
`PROTRUSION_DEV_MM = 0.8` (proeminência mín.) · `CONTAIN_COVERAGE = 0.99` (abaixo,
avisa) · `FIT_TOL_MM = 0.2` · `BEZIER_GUIDE_MM = 0.5` · `CORNER_ANGLE_DEG = 40.0` ·
`RASTER_PPM = 16.0` · `OUTLINE_COLOR = "#ff00ff"` / `OUTLINE_FILL_OPACITY = 0.25`.

## Decisões

Venv isolado (só este tooling depende de pip). **1º passo = medir pelos marcadores ArUco**:
homografia imagem→mm sobredeterminada (32 marcadores × 4 cantos, RANSAC) → escala **uniforme** e
em **mm verdadeiros** (validada: lado 15,87 vs 16 mm, σ 0,12). A retificação **recorta o miolo
branco** → segmentação trivial (colorido OU cromático OU escuro sobre branco, fundo amostrado na
borda). **Traçado padrão = POCKET por quadrante** (ideia do usuário): em vez do contorno mais
fiel, a **cavidade onde a peça encaixa** — prioridade dupla, **cabe** (pocket ≥ objeto) e fica
**justo** (mais pontos = mais apertado); saliências locais ganham âncora p/ a curva não
arredondar por cima. **Sem ganho na etapa 1** (`--clearance 0`): tamanho real, folga **a
jusante**. No **modo fiel** (`--faithful`) a bbox é snapeada na dimensão medida. **Paralaxe
pela altura** nenhuma base corrige — só mede e avisa. SVG = só contorno + preenchimento
translúcido. Sem referência desenhada à mão. **Objetivo:** alimentar **gridfinity
personalizável** a partir do contorno medido.

## Testes

`tests/test_photo_to_outline.py` + `tests/test_calibration_target.py` +
`tests/test_outline_editor.py` (`unittest`, via `run_image_tests.py`).
**Contagem canônica: 113/113 verde** (única fonte; os guias só dizem "verde"). Níveis:

- **A. Unidade (puro):** `polygon_area`/`ensure_ccw` (sinal, CCW); `douglas_peucker` (reduz
  vértices, preserva bbox); `chaikin` (baixa o ângulo máx.); `enforce_min_radius`
  (`min_corner_radius ≥ r_min`); `px_per_mm`; `homography_from_corners`+`apply_homography`
  (recupera 4 cantos); `coverage`/`boundary_roughness`; **Bézier** (`fit_closed_beziers` fita
  círculo em poucas cúbicas; `_corner_indices` acha 4 cantos). `TestAnchoredFit`: todos os nós
  G1; o **POCKET** ancora 1 extremidade/quadrante, respeita o **teto** (estrela côncava: livre
  usa muitas, teto 4 sai com ≤4) e **contém a peça** (coverage ~1) em convexa e côncava.
  `TestProtrusionAnchors`: saliência no meio de aresta ganha âncora, o pocket a alcança, círculo
  **não** gera âncora espúria, nó G1.
- **B. Sintético ArUco (`TestRectifyAruco`):** numpy gera a cena (marcadores + objeto de tamanho
  conhecido); `rectify` devolve canvas métrico, escala uniforme `1/PX_PER_MM`, `conf` 1,0;
  recupera o tamanho real **inclusive sob keystone**; aborta sem marcadores; `estimate_tilt_deg`
  ≈ 0 frontal, cresce sob warp.
- **B2. Histerese de borda (`TestDeshadowHysteresis` + `TestRimToeHysteresis`):** dois canvas
  espelhados. (1) bisel preto cromático + núcleo + sombra cinza → `--shadow remove` **recupera o
  bisel** e **rejeita a sombra**; o piso de saturação (`SEG_WEAK_SAT_MIN`) é o separador (zerá-lo
  infla a base). (2) corpo colorido + toe laranja + sombra cinza → a mesma histerese **recupera
  o toe** e **para na sombra**.
- **B3. Subtrator por textura (`TestTextureShadowSubtractor`):** corpo cinza texturado encostado
  numa sombra projetada lisa e mais clara. `--shadow texture` **mantém o corpo** e **recorta a
  sombra**, enquanto o corte de valor sozinho (`--val-frac` alto) a engloba. `TestValFrac`: o
  `--val-frac` alto captura o corpo cinza-neutro que o default 0,30 perde.
- **B4. Regularização da silhueta (`TestRegularizeSilhouette`):** remove serrilha mantendo a área e
  o tamanho macro; `preserve_convex=True` (`--mask-smooth-keep-bumps`) **preserva o ressalto
  convexo** que o modo isotrópico arredonda, ainda preenchendo a reentrância côncava.
- **C. Ponta-a-ponta (`thermpro.jpg`, skip se ausente — `TestEndToEndThermpro`):** 32/32
  marcadores; escala plausível; no **modo ilimitado** a peça cabe (`coverage ≥ 0,99`), linha
  limpa, **bbox do SVG = dimensão medida**; no **default (pocket teto 4)** o pocket **contém** a
  peça (`coverage ≥ 0,99`) ficando ≥ objeto; `min_corner_radius` (sem bicos); contorno único
  fechado, poucos nós.
- **D. Alvo de calibração (`test_calibration_target.py`).** *Layout puro* (`TestTargetLayout`):
  determinístico; IDs únicos sequenciais; nº de marcadores ≤ capacidade e ≥ 8; tudo dentro da
  margem branca; nenhum marcador invade o miolo; miolo comporta o thermpro; ordem de cantos
  ArUco. *Detecção sintética* (`TestTargetDetection`, OpenCV): renderiza → `detectMarkers` acha
  todos os IDs; `findHomography` recupera o lado de cada marcador = `marker_mm`, uniforme sob
  perspectiva conhecida (prova que o alvo é detectável e métrico **antes de imprimir**).
- **E. Editor de nós (`test_outline_editor.py`, núcleo puro).** `cubics_through_nodes` ("re-traçar",
  a ÚNICA geometria do editor): passa por cada nó, encadeado/fechado, **todos os nós G1** (tangente
  compartilhada), anel de nós vira contorno **simples** (sem auto-cruzar). Ops de edição (`move`/
  `insert`/`delete`) preservam ordem e ≥ 3 nós; `nearest_node`/`nearest_segment`. Transforms
  `mm_to_px`/`px_to_mm` ida-e-volta. A view tkinter é glue fino e **não** é instanciada (runner
  headless); o Finalizar grava EXATAMENTE a curva exibida (WYSIWYG), sem recalcular.
- **F. Saída/CLI (`TestOutputFitSourceOfTruth`, `TestSvgNameEscaping`, `TestCliDictValidation`,
  `TestMakeTargetCli`).** `_fit_for_output` é a **fonte única** do ajuste emitido (.svg final,
  overlay Inkscape e métricas — o overlay recebe a MESMA `--symmetry`; snap de bbox só no modo
  fiel); o `name` (arquivo/`--name`) entra **escapado** no SVG (nome hostil não injeta markup nem
  quebra o XML); `--dict` restrito às `choices` da tabela `DICT_CAPACITY` nos dois CLIs e
  `target_layout` levanta `ValueError` p/ dicionário desconhecido. `TestCubicRoots`: raiz DUPLA
  achada apesar do arredondamento float (tolerância relativa no `det`; antes `det == 0` exato
  perdia a raiz e um cruzamento tangente do eixo sumia). Robustez do layout: borda que não
  comporta 2 marcadores com o vão mínimo recebe **1 centrado** (nunca um par quase-sobreposto)
  e página pequena demais (miolo degenerado) levanta `ValueError`. `estimate_tilt_deg` recebe a
  homografia mm→imagem PRONTA (o inverso da que `rectify` já resolveu — sem 2º RANSAC).
  `TestEditFlowGuards`: `--edit` com detecção degenerada (cub0 vazio) aborta com erro ANTES de
  abrir o editor, e editor devolvendo lista vazia não grava nada (antes: crash em `min()` de
  bbox vazia ao Finalizar). `TestSymmetrizeBeziers`: 2 cruzamentos do eixo → espelhado, fechado
  e simétrico; **>2 cruzamentos** (côncava através do eixo: 2+ arcos no lado mantido, cada
  arco+espelho = laço separado) → **fallback com aviso**, contorno original intacto (antes só o
  1º arco sobrevivia e o resto era descartado em silêncio).
