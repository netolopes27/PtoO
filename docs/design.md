# 12 — Foto → contorno (SVG em mm a partir de foto sobre a base ArUco)

Front-end **fotográfico** da cadeia de item holder: dada uma **foto** de uma ferramenta apoiada na **base de
calibração impressa** (moldura de marcadores ArUco + miolo branco — `tools/base.svg`), produz um **SVG em
milímetros** — fundo branco, contorno preto — com o **contorno externo** da peça, já corrigido de
perspectiva/inclinação pelos marcadores, dimensionado em **mm verdadeiros** e **suavizado para impressão 3D**
(sem cantos de 90°, sem bicos afiados). A saída alimenta `tools/svg_to_scad.py` → `ItemPoly` →
`gridfinity_itemholder(..., item=ItemPoly(...))` (Spec 11), fechando o fluxo foto → caixa custom.

**Natureza:** tooling Python **fora do OpenSCAD** (igual `tools/svg_to_scad.py`), recurso novo — **não** é
engenharia reversa do `.scad`. Por exigir visão computacional, roda num **venv isolado** (`tools/.venv/`) com
`numpy` + `opencv-python`; a suíte OpenSCAD segue 100% stdlib. **Idioma:** código/identificadores/arquivos em
inglês; esta doc e os comentários em pt-BR.

**Arquivos:** `tools/photo_to_outline.py` · `tools/calibration_target.py` (layout do alvo, puro) ·
`tools/make_calibration_target.py` (gera o SVG do alvo) · `tools/base.svg` (alvo gerado) · `tools/requirements.txt` ·
venv `tools/.venv/` · **Testes:** `tools/tests/test_photo_to_outline.py` + `tools/tests/test_calibration_target.py`
(runner `tools/tests/run_image_tests.py`) ·
**Entrada/saída:** `tools/thermpro.jpg` (foto do ThermoPro na **base ArUco** `tools/base.svg`) → `tools/thermpro.svg`
(gerado). O contorno é tirado **direto do JPG** (escala pelos marcadores) — sem referência desenhada à mão.

## Alvo de calibração impresso — base "moldura ArUco + centro branco"

A base de calibração é uma **moldura de marcadores ArUco** ao redor de uma folha **A4**, com **miolo branco liso**
onde o objeto é apoiado. Substituiu a grade anônima de quadrados (escala correta, mas com 3 fraquezas: orientação
ambígua, casamento por linha grossa só sub-px via Hough, e **linha preta confundível com a borda preta do objeto**).
Co-projetada com o detector → cada marcador tem **ID único** (zero ambiguidade de orientação, robusto a oclusão),
cantos **sub-pixel** (homografia precisa, menos código próprio — `cv2.aruco` nativo no OpenCV 4.13, sem dependência
nova) e, sobretudo, **segmentação trivial**: o objeto fica sobre branco, **sem nenhuma linha** para confundir. O
`tool` **gera a própria base** (`make_calibration_target.py` → `tools/base.svg`), garantindo que *o impresso == o
que o detector assume*. **Validado na foto real** (`thermpro.jpg`): 32/32 marcadores, lado reprojetado 15,87 mm
(alvo 16), inclinação ~1°. Inclui um **anel-guia** cinza-claro (círculo concêntrico + cruz) no miolo: só aparece
redondo na tela quando a câmera está no nadir (sob inclinação vira elipse, `cos θ = eixo_menor/eixo_maior`) —
auxílio visual ao enquadrar; o cinza fica acima do limiar de segmentação, então não polui o contorno.

- **`tools/calibration_target.py` (PURO, sem OpenCV — fonte única do layout):** `target_layout(page, page_margin,
  marker_mm, inner_pad, min_gap, dict_name)` → dict com `page`, `page_margin`, `marker_mm`, `dict`, `capacity`,
  `modules`, `inner_rect` (retângulo branco do objeto) e `markers` (lista de `Marker(id,x,y,size)`, IDs sequenciais,
  **moldura de uma espessura**, miolo livre). `Marker.corners_mm()` devolve os 4 cantos na **ordem ArUco** (tl, tr,
  br, bl; Y para baixo). `homography_correspondences(layout)` → `[(id, [4 cantos mm]), …]` = **contrato que o
  detector (`photo_to_outline.aruco_correspondences`) consome** (casa cantos detectados ↔ mm → `findHomography`).
  `A4_LANDSCAPE`/`A4_PORTRAIT`,
  `DICT_CAPACITY`/`DICT_MODULES`. Defaults: A4 paisagem, margem **10 mm** (impressão sem sangria), marcador **16 mm**,
  `inner_pad` 6 mm, `DICT_4X4_50` → **32 marcadores**, miolo branco **233×146 mm**.
- **`tools/make_calibration_target.py` (renderiza o SVG):** marcadores como **retângulos pretos vetoriais**
  (run-length por linha de módulos, `cv2.aruco.generateImageMarker` a 1 px/módulo → nítido no papel), fundo branco
  com margem, **marcas de canto** cinza-claro do miolo e instrução de **impressão a 100%**. CLI: `--out`,
  `--orientation`, `--page-margin`, `--marker-mm`, `--inner-pad`, `--dict`. Aborta se nº de marcadores > capacidade
  do dicionário.

> ⚠️ Limite físico que **nenhuma** base corrige: o objeto tem altura → o topo flutua sobre o plano do papel
> (paralaxe), inflando/deslocando o contorno. Mitigado só **fotografando o mais perto do nadir** (de cima).

## Pipeline (5 estágios)

1. **Detectar a moldura ArUco + RETIFICAR por HOMOGRAFIA (PRIMEIRO PASSO).** A dimensão real do objeto sai daqui.
   `cv2.aruco.detectMarkers` acha os marcadores e seus cantos **sub-pixel** (`detect_markers`); o ID de cada um casa
   com seus 4 cantos **nominais em mm** via `calibration_target.homography_correspondences` (`aruco_correspondences`).
   `findHomography(RANSAC)` resolve a transformação **imagem→mm** sobre todos os cantos casados (homografia
   sobredeterminada — robusta). **Retifica recortando o MIOLO BRANCO** para um canvas métrico de escala **UNIFORME**
   `PX_PER_MM` px/mm (compõe mm→px(canvas) ∘ imagem→mm e `warpPerspective`, `borderValue` branco): os marcadores e o
   anel-guia ficam **fora** do recorte → o segmentador vê só objeto sobre branco. Também estima a **inclinação** da
   foto vs o nadir (`estimate_tilt_deg`, decompõe a pose com intrínseca aproximada) e **avisa** se passar de
   `TILT_WARN_DEG` (a paralaxe pela altura cresce com o ângulo). Devolve `(rectified, mm_per_px, mm_per_px, conf)`
   (`conf` = fração de marcadores detectados); menos de `MIN_MARKERS` → `GridDetectionError`.
2. **Segmentar (objeto sobre branco).** `segment_tool`: o fundo é o **miolo branco conhecido** e o objeto está
   centrado, então a **moldura da borda** do canvas é fundo puro — amostrada (mediana HSV) p/ modelar o branco
   (**auto-adapta** ao balanço de branco/iluminação). Um pixel é **objeto** se for **colorido** (saturação ≥ fundo +
   `SEG_SAT_MARGIN`, ex. a borda laranja) **OU escuro** (brilho ≤ `SEG_VAL_FRAC`×fundo, ex. a moldura preta); a
   **sombra** suave é dessaturada e só um pouco mais escura → fica no fundo. Morfologia `open`/`close` (abre
   respingos, fecha vãos), **maior componente conectado** e preenche buracos internos (display, texto) → contorno
   cheio. Aposentou a máscara `NOT(verde)` da base antiga.
   **Sombra / topo preto (opcional, `--shadow remove`).** O corte único de escuro (`SEG_VAL_FRAC`) corta *dentro* da
   rampa preto→sombra→papel, **comendo e serrilhando a borda do topo preto** (objeto fica mais baixo do que é).
   `--shadow remove` liga uma **histerese** (estilo Canny): o **núcleo preto certo** (≤ `SEG_VAL_FRAC`×fundo) cresce
   pelos pixels escuros vizinhos (≤ `SEG_VAL_WEAK_FRAC`×fundo) por **dilatação geodésica de alcance limitado**
   (`SEG_SHADOW_GROW_MM`) até bater no papel claro — recuperando a borda real. O limite é essencial: sem ele o
   crescimento inunda **todo o anel de sombra de contato** (a peça inteira é um só componente fraco que toca o
   núcleo). A fina sombra que entra **engorda** o contorno (a peça cabe) — o oposto do "topo comido". **Padrão `off`**.
2b. **Simetria (opcional, `--symmetry`).** `symmetrize_mask`: quando o objeto é simétrico, a metade esquerda e a
   direita (ou topo/baixo) são **duas medições do MESMO contorno** → espelhar e fazer a **média** cancela o ruído
   assimétrico da foto (sombra/realce de um lado só, serrilhado) e **força a simetria perfeita**. Acha o eixo a
   partir do **centroide** e refina por **máx. IoU** entre a máscara e seu espelho (±`SYM_SEARCH_MM`); a média de
   duas formas é feita pelo **campo de distância COM SINAL** (`_signed_distance`: >0 dentro, <0 fora) — médio os dois
   campos e corto em 0 (média morfológica, não AND/OR que enviesariam p/ dentro/fora). `vertical` = eixo vertical
   (esq./dir.), `horizontal` = topo/baixo, `both` = os dois em sequência. **Padrão `none`** (sem simetria).
3. **Contorno externo.** `extract_outline`: `findContours(RETR_EXTERNAL)` → maior área; px→mm com escala
   **por eixo** (`mm_per_px_x`, `mm_per_px_y`); inverte Y. A bbox dele = **dimensão real medida** do objeto.
4. **Suavizar p/ impressão (`process_for_print`).** `enforce_min_radius` (filete morfológico: nenhum canto convexo
   abaixo de `--min-radius`, o **bico** vira arco; + **dilatação `--clearance`** = margem de encaixe) → **low-pass
   forte** `lowpass_closed(--smooth-mm)` (remove o serrilhado de alta frequência herdado da foto, preservando as
   features reais ≫ smooth-mm) → decimação `approxPolyDP` (≈0,02 mm). Garante fechado, CCW, sem auto-interseção.
   **Etapa 1 SEM GANHO:** o padrão é `--clearance 0` → o contorno sai no **tamanho REAL** da peça; a folga de
   encaixe é aplicada **depois** (ver estágio 5 / Decisões). (Este estágio alimenta o modo alternativo `--tol-fit`;
   o modo padrão ancorado parte da silhueta crua.)
5. **Ajustar curvas + emitir SVG (`polygon_to_svg`).** Saída feita **só de Béziers cúbicas**, em **poucos nós**,
   contendo a peça. **Modo padrão — ANCORADO NAS EXTREMIDADES** (`fit_closed_beziers_anchored`): denoisa a silhueta
   (low-pass `--smooth-mm`), fixa âncoras nos **pontos mais distantes do objeto** (vértices do fecho convexo,
   destilados por RDP `--simplify`) e, **entre âncoras**, ajusta cúbicas **contidas** (Schneider + busca da maior
   tolerância cuja curva não penetra a peça além de `eps`, via `distanceTransform`). Ancorar nas extremidades
   **garante que a peça cabe** (a cavidade alcança bico/calcanhar/cantos). **Todo nó é SUAVE (G1):** a tangente em
   cada âncora é **compartilhada** entre os dois trechos vizinhos (corda pelos vizinhos imediatos, `_anchor_tangents`),
   então não há bico — saída limpa, fácil de imprimir e de editar no Inkscape (todos os nós são "smooth"). `--simplify`
   dá o trade-off **nº de nós × justeza** (maior = menos âncoras/nós, mais "hull"; menor = mais justo, mais nós);
   `--max-nodes N` impõe um **limite RÍGIDO** de cantos (`_limit_anchors` remove as âncoras menos significativas —
   as mais quase-colineares — até sobrarem ≤ N), p/ FORÇAR um contorno mais simples. **A bbox da saída
   é fixada (snap, por eixo) na dimensão real medida do objeto** (`_scale_cubics_to_bbox`) → o SVG tem o **tamanho
   exato medido pela grade**. Emite **contorno + preenchimento translúcido** (`<path>` `C`, `fill:OUTLINE_COLOR;
   fill-opacity:OUTLINE_FILL_OPACITY;stroke:OUTLINE_COLOR` — cor destacada quase transparente que **sobrepõe o objeto**
   p/ conferir cobertura) em mm; lido por `svg_to_scad.py` (que usa só a geometria do `d`, ignora o estilo). **Modos alternativos:** `--tol-fit` (mínimo por contenção a partir do guia
   `process_for_print`, `fit_closed_beziers_contained`); `--polyline` (polilinha crua `L`). A folga de impressão é
   somada **a jusante** (`clearance` do `gridfinity_itemholder`, que aplica `offset()`, ou escalar o SVG ~0,6 %).

## API — funções puras (testáveis sem imagem)

**Geometria de polígono** (`pts` = `list[(x,y)]` ou `ndarray Nx2`, em mm salvo nota):
- `polygon_area(pts)` (shoelace, com sinal → winding); `signed_area`; `ensure_ccw(pts)`.
- `is_closed(pts, tol=1e-6)`; `close_polygon(pts)` / `dedup_closing_point(pts)`.
- `bbox(pts)` → `(min_x, min_y, max_x, max_y)`; `size(pts)` → `(w, h)`.
- `douglas_peucker(pts, eps)` → polilinha simplificada.
- `chaikin(pts, iterations, closed=True)` → polígono suavizado (corner-cutting 1/4–3/4).
- `lowpass_closed(pts, win_mm, step)` → low-pass (Hann circular) de x(s)/y(s): remove ripple/serrilhado.
- `corner_angles(pts, closed=True)` → ângulo interno por vértice (graus).
- `corner_radii(pts, closed=True)` → raio do círculo osculador por vértice (mm); `min_corner_radius(pts,
  window=0.8)` (circunraio com vizinhos afastados ~`window` mm — sem o viés do estimador de 3 vizinhos imediatos).
- `enforce_min_radius(pts, r_min, clearance=0, closed=True)` → arredonda TODO canto a ≥ `r_min` via
  abertura+fechamento morfológico (disco) e dilata `clearance` (margem de encaixe).
- `resample_uniform(pts, step, closed=True)`.
- `boundary_roughness(pts, win_mm=2.0)` → aspereza (desvio máx. contorno vs seu low-pass): mede "linha limpa".
- `coverage(outer, inner)` → fração de `inner` contida em `outer` (1.0 = a peça cabe no pocket).
- **Ajuste de Bézier (Schneider):** `fit_closed_beziers(poly, tol, corner_angle)` → lista de cúbicas
  `(p0,c1,c2,p3)`; `bezier_point`, `flatten_beziers(cubics, seg)`, `_corner_indices` (cantos cusp, NMS circular),
  `_fit_one_cubic` (mínimos quadrados com tangentes fixas), `_fit_cubic_recursive` (split no ponto de maior erro).
- **Ancorado nas extremidades (modo padrão):** `fit_closed_beziers_anchored(silhouette, smooth_mm, simplify_mm,
  eps, max_nodes=0)` → denoisa, ancora nos vértices dominantes do fecho convexo e ajusta cúbicas contidas entre eles,
  com **tangentes compartilhadas → todos os nós suaves (G1)**; `hull_anchor_indices(rp, simplify_mm)` (extremidades =
  fecho convexo destilado por RDP), `_anchor_tangents(rp, anchors)` (tangente de marcha por âncora, base do nó suave),
  `_limit_anchors(rp, anchors, max_nodes)` (decimação das âncoras menos significativas p/ o limite rígido `--max-nodes`),
  `douglas_peucker_idx(pts, eps)` (RDP devolvendo índices), `_fit_segment_contained` (maior tolerância sem penetrar o
  piso além de `eps`).
- **Mínimo por contenção (modo `--tol-fit`):** `fit_closed_beziers_contained(guide, silhouette, c_fit, eps)` → menor nº de cúbicas
  cuja curva contém a peça (maior tolerância aprovada); `_floor_field` (mapa de profundidade dentro da peça+`c_fit`,
  via `distanceTransform`), `_max_penetration`/`_beziers_max_penetration` (verificam contenção).
- **Snap de dimensão:** `_scale_cubics_to_bbox(cubics, target_w, target_h)` → escala por eixo p/ a bbox achatada
  ficar exatamente no tamanho medido do objeto.

**Escala + retificação (homografia ArUco):**
- `px_per_mm(spacing_px, mm)` → px/mm; `mm_per_px(...)` = inverso (utilitários genéricos).
- `homography_from_corners(src4, dst4)`/`apply_homography(H, pts)` (homografia genérica de 4 pontos).
- **Detecção ArUco:** `detect_markers(gray, dict_name)` → `(corners, ids)` (cantos sub-pixel via `cv2.aruco`);
  `aruco_correspondences(corners, ids, layout)` → `(img_pts, mm_pts)` casando ID↔cantos nominais (contrato de
  `calibration_target.homography_correspondences`); `estimate_tilt_deg(img_pts, mm_pts, shape)` → inclinação (graus)
  vs o nadir, decompondo a homografia mm→pixel com intrínseca aproximada (aviso de paralaxe).
- Layout/contrato: vêm de **`calibration_target.py`** (puro): `target_layout(...)`, `default_layout()`,
  `homography_correspondences(layout)`, `Marker.corners_mm()`.

**Comparação / validação (suporte aos testes):**
- `coverage(outer, inner)` → fração de `inner` contida em `outer` (encaixe; 1.0 = a peça cabe).
- `boundary_roughness(pts, win_mm)` → aspereza (limpeza da linha).

## API — pipeline (I/O)

`load_image(path)`; `rectify(img, dict_name="DICT_4X4_50")→(rectified, mm_per_px, mm_per_px, conf)`;
`segment_tool(img, deshadow=False)→mask`; `symmetrize_mask(mask, axis, ppmm)→mask`; `extract_outline(mask, mm_per_px_x, mm_per_px_y)→pts_mm`; `process_for_print(...)→pts_mm`;
`polygon_to_svg(pts_mm, name, silhouette=…)→str`; `write_overlay(rect, mask, path)` (overlay PNG de conferência);
`write_overlay_svg(rect, cubics, mm_per_px_x, mm_per_px_y, path)` (overlay SVG editável: foto embutida + Béziers);
`generate_outline(..., overlay_path=None, overlay_svg_path=None, return_silhouette)`. Orquestrador `main(argv)`.

### CLI
```
python tools/photo_to_outline.py --in tools/thermpro.jpg --out tools/thermpro.svg \
    [--dict DICT_4X4_50] [--min-radius 1.5] [--smooth-mm 8] [--clearance 0] \
    [--shadow off|remove] [--symmetry none|vertical|horizontal|both] [--inkscape] \
    [--simplify 2.0] [--max-nodes 0] [--tol-fit --fit-tol 0.2 --guide 0.5 --c-fit 0] [--polyline] \
    [--name thermpro] [--debug-dir tools/_debug]
```
**Pré-requisito:** imprima `tools/base.svg` em A4 a 100%, apoie a peça no **centro branco** e fotografe de cima (o
mais perto do nadir, mirando pelo anel-guia). `--dict` deve casar com o dicionário da base impressa. `--simplify`
controla a densidade de âncoras (nº de nós × justeza) no modo padrão (ancorado); `--max-nodes N` impõe um limite
rígido de nós/cantos (0 = automático). `--shadow remove` liga a histerese
de escuro (recupera a borda do **topo preto** que o corte único comia; ver estágio 2). `--symmetry` impõe a simetria
do objeto (espelho + média das metades; ver estágio 2b) p/ limpar o contorno. **A cada execução** grava-se, **antes
do `.svg`** e ao lado dele (prefixo `_overlay_`, underscore inicial = rascunho ignorado pelo git), o overlay PNG de
conferência **`_overlay_<nome>.png`** (contorno segmentado, já com a simetria, em vermelho sobre a foto retificada —
validação rápida da segmentação/iluminação). **`--inkscape`** gera *também* a saída intermediária **editável no
Inkscape** **`_overlay_<nome>.svg`**: a foto retificada embutida como `<image>` numa camada travada + os **mesmos
Béziers do `.svg`** (com o mesmo preenchimento translúcido) numa camada editável, tudo no referencial métrico em mm —
ajusta-se os nós sobre a foto, apaga-se a camada da foto e exporta-se o contorno corrigido na escala real. `--debug-dir`
grava PNGs intermediários (retificada, máscara, contorno) p/ diagnóstico. Marcadores insuficientes → **aborta com
mensagem clara**. A saída sai no **tamanho real medido pelos marcadores** (a bbox é fixada na silhueta), **sem ganho**
(`--clearance 0`); a folga de impressão é aplicada a jusante (`clearance` do item holder, ou escalar o SVG).

## Constantes (defaults)

`PX_PER_MM = 8.0` (resolução do canvas métrico) · `DICT_NAME = "DICT_4X4_50"` (deve casar com a base impressa) ·
`MIN_MARKERS = 8` (mínimo p/ homografia confiável) · `TILT_WARN_DEG = 5.0` (aviso de inclinação) ·
`SEG_SAT_MARGIN = 45` / `SEG_VAL_FRAC = 0.30` (segmentação: colorido OU escuro vs o fundo branco amostrado) ·
`SEG_VAL_WEAK_FRAC = 0.65` / `SEG_SHADOW_GROW_MM = 2.0` (histerese de escuro do `--shadow remove`: corte fraco e
alcance máx. do crescimento do núcleo preto) ·
`SYM_SEARCH_MM = 4.0` (busca do eixo de simetria ± em torno do centroide, máx. IoU) ·
`MIN_RADIUS_MM = 1.5` · `SMOOTH_MM = 8.0` · **`CLEARANCE_MM = 0.0`** (etapa 1 sem ganho) · `ANCHOR_SIMPLIFY_MM = 2.0` ·
`MAX_NODES = 0` (limite rígido de nós/cantos; 0 = automático) ·
`ANCHOR_EPS_MM = 0.08` · `FIT_TOL_MM = 0.2` · `BEZIER_GUIDE_MM = 0.5` · `CORNER_ANGLE_DEG = 40.0` · `RASTER_PPM = 16.0` ·
`OUTLINE_COLOR = "#ff00ff"` / `OUTLINE_FILL_OPACITY = 0.25` (cor destacada + preenchimento quase transparente da saída).

## Decisões

Venv isolado (só este tooling de visão depende de pip). **Primeiro passo = medir o objeto pelos marcadores ArUco**:
homografia **imagem→mm** sobredeterminada (32 marcadores × 4 cantos sub-pixel, RANSAC) → escala **UNIFORME** e em
**mm verdadeiros**, validada na foto real (lado reprojetado 15,87 vs 16 mm, σ 0,12; inclinação ~1°). Substituiu a
detecção de **grade** (Hough + treliça + autocorrelação, ~20 funções): a moldura ArUco resolve as 3 fraquezas da
grade (orientação ambígua, casamento por linha grossa, linha preta confundível com a borda do objeto) e dá a
referência *medida, identificada e sempre visível* (fica na moldura, o objeto nunca a cobre). A retificação **recorta
o miolo branco** → segmentação trivial: objeto **colorido OU escuro** sobre branco, com o fundo amostrado na borda
(auto-adapta à luz); aposentou a máscara `NOT(verde)`. **A bbox do SVG é fixada na dimensão real medida** (snap) → o
tamanho do SVG = o medido pela base, não o inflado pelo ajuste. **Etapa 1 SEM GANHO** (`--clearance 0`): o contorno
sai no tamanho real; a folga de encaixe é aplicada **a jusante** (`clearance` do `gridfinity_itemholder`, que faz
`offset()`, ou escalar o SVG ~0,6 %) — fluxo travado p/ não acumular ganho. **Traçado ancorado nas extremidades**
(ideia do usuário): fixar os pontos mais distantes do objeto (fecho convexo destilado) **garante caber** e gera
transições suaves; entre âncoras, cúbicas contidas justas (poucos nós). `--simplify` é o trade-off nº de nós ×
justeza. Tensão inerente sob "tem que caber": curva suave com poucos nós precisa estufar p/ fora nas concavidades; o
low-pass tira o serrilhado (silhueta crua tem ruído sub-mm, denoisado — o tool real fica contido, e a folga a jusante
cobre o resíduo). **Limite que nenhuma base corrige:** a altura do objeto gera paralaxe (o topo flutua sobre o
papel) — mitigada só fotografando perto do nadir; agora o tool ao menos **mede e avisa** a inclinação. SVG é **só o
contorno, sem fundo**. **Sem referência desenhada à mão** (contorno direto do JPG). Lido por `svg_to_scad.py` sem
mudança; wheel `opencv-python` abi3 cobre Python 3.14.

## Testes

`tools/tests/test_photo_to_outline.py` (Python `unittest`, roda no venv via `run_image_tests.py`). Três níveis:

**A. Unidade (puro):** `polygon_area`/`ensure_ccw` sinal e CCW; `douglas_peucker` reduz vértices preservando bbox;
`chaikin` baixa o ângulo máximo de canto; `enforce_min_radius` → `min_corner_radius ≥ r_min`; `px_per_mm`;
`homography_from_corners` + `apply_homography` recupera 4 cantos conhecidos; **`coverage`** (1.0 quando contido,
baixo quando transborda) e **`boundary_roughness`** (~0 p/ círculo liso, alto p/ dente-de-serra); **ajuste de
Bézier** (`fit_closed_beziers` fita círculo em ≤12 cúbicas com erro < 0,3 mm; `_corner_indices` acha 4 cantos no
quadrado — NMS circular). Inclui **`TestAnchoredFit`** (modo padrão): `douglas_peucker_idx` mantém os cantos
dominantes; `hull_anchor_indices` ≈ 4 cantos num retângulo; `fit_closed_beziers_anchored` contém um círculo com
poucas cúbicas suaves; mais `--simplify` → menos (ou igual) nós; **todos os nós são suaves (G1)** — tangentes que
chegam/saem colineares em cada junção; **`--max-nodes` limita os cantos** (círculo convexo sai com exatamente o nº
de âncoras pedido, ainda contendo a peça).

**B. Sintético ArUco (`TestRectifyAruco`, numpy gera a cena):** `_aruco_scene` renderiza os marcadores nas posições
nominais com um objeto escuro de tamanho conhecido no centro. O `rectify` devolve um **canvas métrico** do tamanho do
miolo (`inner × PX_PER_MM`), escala **uniforme** = `1/PX_PER_MM`, `conf` = 1,0 (todos detectados); o pipeline
**recupera o tamanho real do objeto** (40×30 mm ± 1) inclusive **sob keystone** (homografia ArUco remove a
perspectiva); **aborta** (`GridDetectionError`) sem marcadores; `estimate_tilt_deg` ≈ 0 na cena frontal e cresce
sob warp.

**C. Ponta-a-ponta na foto real (`thermpro.jpg`, skip se ausente — `TestEndToEndThermpro`):** **32/32 marcadores**
(`conf` = 1,0); escala plausível dos marcadores (largura/altura 55–90 mm); o contorno EMITIDO é o **ancorado**
(clearance=0, snap na silhueta); **encaixe** `coverage(saída, silhueta) ≥ 0,99` (a peça cabe — extremidades
ancoradas; ruído sub-mm de sombra denoisado coberto pela folga a jusante); **linha limpa** `boundary_roughness <
0,15 mm`; regra de impressão `min_corner_radius ≥ 1,0 mm` (sem bicos afiados); contorno único fechado; **poucos nós**
(≤ 45, e < metade do polyline); **dimensão do SVG = dimensão medida do objeto** (bbox bate com a silhueta dentro de
0,05 mm).

**D. Alvo de calibração (`test_calibration_target.py`).** *Layout puro* (`TestTargetLayout`): determinístico; IDs
únicos sequenciais; nº de marcadores ≤ capacidade do dicionário e ≥ 8 (homografia robusta); **tudo dentro da margem
branca**; **nenhum marcador invade o miolo** (moldura só); miolo comporta o thermpro (≥ 130×120 mm); ordem de cantos
ArUco. *Detecção sintética* (`TestTargetDetection`, precisa OpenCV): renderiza os marcadores numa "foto" numpy →
`cv2.aruco.detectMarkers` acha **todos os IDs**; `findHomography` recupera o lado de **cada** marcador = `marker_mm`;
e, sob **perspectiva conhecida**, a homografia devolve lados **uniformes = marker_mm em todo o campo** (prova que o
alvo é detectável e métrico **antes de imprimir**).
