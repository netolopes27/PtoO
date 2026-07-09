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
**Testes:** `tests/test_photo_to_outline.py` + `tests/test_calibration_target.py` +
`tests/test_outline_editor.py` (runner `tests/run_image_tests.py`). **E/S:** `thermpro.jpg` →
`thermpro.svg`.
**Imagens dos itens:** as fotos de entrada e as saídas (`<name>.svg` + `_overlay_*`) dos itens
mapeados ficam em `images/` (a CLI grava o SVG ao lado da entrada); só `base.svg` e a amostra
`thermpro.jpg` ficam na raiz. Convenção em [AGENTS.md](../AGENTS.md) §Convenções.

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
     volta pela porta do cromático em fundo de papel saturado. Padrão `off`.
     **Refino de borda por watershed (v0.8, embutido no `texture`):** a sombra de **contato/UMBRA**
     é escura (não "mais clara") e passava pelo recorte, inflando a silhueta ~4–5 mm. Depois do
     recorte, `_refine_edge_watershed` re-decide a fronteira pelo **gradiente** (watershed com
     marcadores: FG = miolo erodido `SEG_WS_ERODE_MM` **menos** o liso-e-meio-claro
     `SEG_WS_FG_VAL_FRAC`; BG = fora da máscara dilatada `SEG_WS_BAND_MM`): a borda física
     peça↔fundo é um *degrau* de V e a sombra↔papel é *rampa* suave — a inundação do papel
     atravessa a rampa e a da peça esbarra no degrau. Resíduo típico: ~0,5–1,5 mm.
2b. **Fusão 2-fotos (opcional, `--in2`, v0.9).** Para **sombra dura** (sol) que nenhum `--shadow`
   resolve e p/ **metal claro** que some no papel: duas fotos da mesma peça sobre a mesma base,
   mudando só o **lado da luz** (girar base+peça juntas ~180°). As duas retificações ancoram no
   mesmo alvo impresso → mesmo canvas métrico. Três passos (`fuse_masks`):
   - **Registro rígido** (`_register_masks`): rotação (quartos {0,90,180,270}° + refino fino
     ±`FUSE_ANGLE_DEG`, em torno do centroide da máscara 2) e translação (±`FUSE_SEARCH_MM`,
     semente = diferença de centroides), pontuadas por **IoU × textura** (ZNCC dos grays na
     sobreposição; o IoU sozinho é ambíguo — sombra∩sombra infla a rotação errada em peça
     retangular; o refino fino roda em TODOS os quartos antes de eleger). O registro roda nas
     máscaras **limpas** (sem faint-metal) p/ ancorar na peça, não na sombra.
   - **Fusão direcional por pixel disputado:** direção da sombra de cada foto = centroide do
     **lóbulo exclusivo** (pixels só naquela máscara, mín. `FUSE_MIN_LOBE_MM`) relativo ao núcleo
     (AND). O núcleo sempre entra; pixel de lóbulo entra **só no lado iluminado da própria foto**
     ((p−c)·ŝᵢ ≤ 0) — lá a borda dela é limpa (o excesso é paralaxe/peça real); do lado da sombra,
     o excesso É sombra e cai. Sombras p/ o MESMO lado (cosseno > `FUSE_ALIGN_MAX`) → aviso p/
     refotografar (degrada p/ ~AND). `--fuse-grow` (`FUSE_GROW_MM`): dilatação geodésica opcional
     dentro da união p/ resíduo perto da bissetriz.
   - **Predicado faint-metal** (automático no modo 2 fotos, em `segment_tool(faint_metal=True)`):
     S ≥ fundo+`FUSE_FAINT_SAT_MARGIN` e V ≤ `FUSE_FAINT_VAL_MAX`×fundo recupera **metal claro
     liso** (topo de conector ≈ brilho do papel — invisível a colorido/cromático/escuro em luz
     difusa). Readmite a sombra junto, o que só é seguro aqui: a fusão a remove.
   O overlay usa de fundo a foto de **menor lóbulo** (melhor luz), warpada pelo registro.
2c. **Auto-nível (opcional, `--level auto`, 011/F3).** `level_rect_and_mask`: corrige a rotação
   **fina** da peça apoiada torta na base. Estima pelo **envelope** (`estimate_level_angle`:
   `cv2.minAreaRect` da maior componente → `snap90` = desvio ao múltiplo de 90° mais próximo,
   mod 90 em [−45°,+45°); recuperou EXATO os ângulos injetados no experimento) e gira `rect` E
   `mask` com a **mesma matriz** (centro da peça; máscara em NEAREST), **sem re-segmentar** —
   overlay e estágios seguintes consomem o par nivelado de graça. Salvaguardas: aplica só em
   `LEVEL_MIN_DEG ≤ |desvio| ≤ LEVEL_MAX_DEG` (abaixo = já nivelado, saída **idêntica**; acima =
   warn e segue); peça ~quadrada/redonda (aspecto < `LEVEL_ASPECT_MIN`) sem reta ≥
   `LEVEL_LINE_MIN_MM` alinhável não é corrigida (num disco o envelope é instável). Roda **antes**
   da simetria (o eixo é sempre v/h — nivelar primeiro é o que faz a simetria encaixar). Sinal:
   girar por **+desvio** (`getRotationMatrix2D`) zera o resíduo (validado em sintético).
2d. **Simetria (opcional, `--symmetry`).** `symmetrize_mask`: num objeto simétrico as duas
   metades são **duas medições do mesmo contorno** → espelhar e fazer a **média** cancela o
   ruído assimétrico e força a simetria. Acha o eixo pelo **centroide**, refina por **máx. IoU**
   (±`SYM_SEARCH_MM`) e faz a média pelo **campo de distância COM SINAL** (`_signed_distance`:
   >0 dentro, <0 fora; média morfológica, não AND/OR). `vertical`/`horizontal`/`both`. Padrão
   `none`.
2e. **Contorno humilde (`--humble`, v0.12 — fallback p/ borda SEM apoio visual).** Roda depois
   da simetria e da regularização (`--mask-smooth-mm`), antes de extrair o contorno.
   `humble_rewrite(mask, gray, ppmm, mode, merge)`: classifica cada ponto do contorno externo
   como **firme** (|Sobel| do cinza retificado, dilatado ±`HUMBLE_GRAD_WIN_MM` como janela de
   tolerância, acima do limiar) ou **incerto**; limiar = **Otsu sobre os valores da própria
   borda** com **teto** `HUMBLE_GRAD_CAP`×piso (senão o Otsu divide uma borda toda forte e chama
   a metade menos contrastada de incerta; medido no thermpro — ver historico §v0.12) e piso
   absoluto `HUMBLE_GRAD_FLOOR`/4×mediana global (papel/JPEG). Limpeza da classificação: fecha
   buracos incertos < `HUMBLE_FIRM_CLOSE_MM`, derruba ilhas firmes < `HUMBLE_FIRM_ISLAND_MM`.
   Depois, por vão incerto entre trechos firmes: **corda reta** se a lasca descartada é **lisa**
   (< `HUMBLE_SLIVER_TEX_FRAC` de pixels com gradiente, ou < `HUMBLE_SLIVER_MIN_MM2`);
   texturizada → **subdivide** ao meio (por arco) e recursa; vão < `HUMBLE_MIN_GAP_MM` ainda
   texturizado → **mantém a borda original + FLAG** (stdout com posição/extensão; overlay pinta
   em **laranja**; camada própria no `--inkscape`). Passada final de **merge (2b)** funde cordas
   adjacentes cujo triângulo de emenda é liso (remove a "tenda" no ápice do halo). Cordas
   densificadas a ~`HUMBLE_CHORD_STEP_MM`/ponto → o `--line-tol` (v0.10) as detecta e emite
   **retas de verdade**. Gatilho: `auto` (default) computa a fração firme em toda execução
   (métrica `firme NN%`) e só ativa abaixo de `HUMBLE_MIN_FIRM_FRAC`, com aviso; `on` força,
   `off` nunca; ignorado com `--faithful`/`--tol-fit` (contradição; avisa se `on`). Quando
   ativa, `sil_ref` (o alvo do `contém`) passa a ser a silhueta **pós-humilde** (racional em
   §Decisões). Borda 0% firme = sem âncora p/ corda → mantém tudo + aviso de que o humilde
   não se aplica.
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
   **Primitivas geométricas (v0.10, default ligado — `--line-tol`/`--arc-tol`):** antes da
   seleção de âncoras, o contorno reamostrado passa por dois detectores (`_detect_line_runs` /
   `_detect_arc_runs`): trecho maximal com desvio à corda < `LINE_TOL_MM` vira **RETA** (fusão de
   colineares; **veto por círculo**: se um círculo de raio plausível ajusta melhor, é arco — um
   círculo grande não vira polígono; pontas recuadas `PRIM_TRIM_MM` p/ o canto virar filete), e
   nos **vãos entre retas** um círculo LSQ (Kasa) com resíduo < `ARC_TOL_MM`, varredura monótona
   e **giro por ponto ≈ passo/r** (canto não é engolido) vira **ARCO**. Emissão via
   `_fit_primitives`: pontas de primitiva = âncoras com **tangente da primitiva** (reta manda
   sobre arco no nó compartilhado; discórdia > ~25° entre primitivas coladas = canto → 
   `_open_corner_gaps` recua as fronteiras e o canto vira trecho livre G1); ponta de reta é
   **deslocada p/ fora** pelo desvio residual (a corda vira reta-suporte: contenção garantida,
   pois estufar cúbica colinear não a move de lado); arco > 90° é dividido (1 cúbica/90°);
   âncoras de quadrante internas às primitivas são **suprimidas** (saliências nunca). Resultado:
   aresta reta é reta de verdade (não arqueia p/ dentro — no Pi a folga caiu de +0.83 p/ +0.07 em
   min-dist 10), canto é filete tangente, e `--min-dist` passa a reger só os trechos livres.
   `--line-tol 0` desliga tudo (caminho legado intacto).
   **Priors de geometria (v0.13, `--corner-radius`/`--shape`, vindos do `--describe` da skill
   /ptoo):** conhecimento DECLARADO pelo usuário vira restrição. `--corner-radius R` — arco
   detectado com raio a ±max(1 mm, 20%) do prior é refit com **raio fixo**
   (`_refit_center_fixed_r`, ponto fixo de Gauss–Newton só no centro; pontas projetadas no
   círculo declarado, só p/ fora): o canto sai com o raio medido, não o estatístico.
   `--shape rect` — pocket **construído** (`_fit_shape_rect`), não ajustado: pose por
   `minAreaRect` da silhueta denoisada, 4 retas + 4 arcos de 90° (raio R, piso `MIN_RADIUS_MM`)
   como 8 cúbicas (kappa), W/H inflados uniformemente o mínimo p/ conter (SDF analítico;
   1 passo basta — inflar os semieixos por d reduz todo SDF ≥ d). Salvaguardas → WARNING +
   fallback genérico: inflação > `SHAPE_INFL_MAX_MM` ou vão modelo→peça > `SHAPE_GAP_MM`
   (peça não é a forma declarada). Com o modelo, `--symmetry` é pulado (o modelo já é simétrico
   na própria pose; espelhar na bbox entortaria a rotação) e as métricas ganham
   `shape rect r=… infl +…` (ou `shape FALLBACK`).
   **Espigões finos (v0.7, `_preserve_spikes`):** o low-pass do `--smooth-mm` recuaria a ponta de
   uma protuberância fina real (gancho da trena) antes da seleção de âncoras; os trechos crus
   proeminentes (recuo ≥ `SPIKE_MIN_RECEDE_MM` e boca ≤ `SPIKE_MAX_WIDTH_MM` — pico de serrilha e
   canto/curvatura macro ficam de fora) são reinjetados em `clean` antes do piso.
   **`contém` honesto (v0.7):** o CLI mede `contém`/`encaixe` contra a silhueta de **referência**
   pré `--mask-smooth-mm` (`sil_ref` de `return_silhouettes=True`), com tolerância de
   profundidade `CONTAIN_TOL_MM` (erosão no `coverage`): penetração rasa de ruído não conta;
   feature removida pela regularização derruba o gate (e `regularize_silhouette` **avisa** quando
   remove saliência convexa ≥ `PROTRUSION_DEV_MM` / `MASK_SMOOTH_WARN_AREA_MM2`).
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
  simplify_mm, eps, faithful=False, min_dist_mm, pocket_eps, symmetry, line_tol_mm, arc_tol_mm,
  shape="off", corner_radius_mm=0)` (priors v0.13: `_fit_shape_rect` constrói o modelo rect;
  `_refit_center_fixed_r` refit de arco com raio fixo); helpers `_quadrant_anchors`,
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
`normalize_illumination(img)→img`; `segment_tool(img, deshadow=False, val_frac, faint_metal=False)→mask`
(`deshadow` ∈ {False/"off", True/"remove", "texture"}; `faint_metal` = predicado de metal claro,
ligado pelo modo 2 fotos); `_refine_edge_watershed(img, mask, Vd, smooth, bg_v)→mask` (refino de
borda do `texture`); `fuse_masks(mask1, mask2, ppmm, search_mm, grow_mm, gray1, gray2, reg1,
reg2)→(fused, reg)` (fusão 2-fotos; `reg1/reg2` = máscaras limpas só p/ o registro; `reg` =
transformação + áreas dos lóbulos) e `_register_masks(m1, m2, ppmm, search_mm, gray1, gray2)→
(angle, center, dx, dy, score)` (registro rígido, testável com máscaras sintéticas);
`snap90(deg)→deg` / `estimate_level_angle(mask, ppmm)→(desvio, centro, motivo)` /
`level_rect_and_mask(rect, mask, ppmm)→(rect, mask, desvio|None)` (auto-nível, `--level`);
`symmetrize_mask(mask, axis, ppmm)→mask`; `humble_rewrite(mask, gray, ppmm, mode="auto",
merge=True)→(mask2, report)` (contorno humilde v0.12, pura/testável com fixtures sintéticas;
`report` = `{firm_frac, active, chords, flags [((cx,cy) mm, ext mm)], flag_runs_px, note}`);
`extract_outline(mask, mm_per_px_x, mm_per_px_y)→pts`;
`process_for_print(...)→pts`; `polygon_to_svg(pts, name, …)→str`; `write_overlay(rect, mask,
path, flag_runs=None)` (PNG de conferência; `flag_runs` = trechos incertos em laranja);
`write_overlay_svg(rect, cubics, mm_per_px_x, mm_per_px_y, path, flag_polylines_mm=None)`
(SVG editável: foto embutida + Béziers + camada "incerto"); `generate_outline(...,
overlay_path, overlay_svg_path, humble="auto", return_humble_report=False)`.
Orquestrador `main(argv)`.

### CLI
```
python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    [--in2 foto2.jpg] [--fuse-grow 0] \
    [--dict DICT_4X4_50] [--min-radius 1.5] [--smooth-mm 8] [--clearance 0] \
    [--shadow off|remove|texture] [--val-frac 0.30] \
    [--symmetry none|vertical|horizontal|both] [--level off|auto] \
    [--humble auto|on|off] [--inkscape] \
    [--simplify 2.0] [--min-dist 10] [--faithful] [--mask-smooth-mm 0] [--mask-smooth-keep-bumps] \
    [--line-tol 0.3] [--arc-tol 0.3] [--corner-radius 0] [--shape off|rect] [--pocket-eps 0.5] \
    [--tol-fit --fit-tol 0.2 --guide 0.5 --c-fit 0] [--polyline] [--edit] \
    [--name thermpro] [--debug-dir _debug]
```
Imprima `base.svg` em A4 a 100%, apoie a peça no centro branco, fotografe perto do nadir.
`--dict` deve casar com a base impressa. `--min-dist` = densidade do pocket (menor = mais justo,
**sem teto de nós**); `--faithful` = modo fiel com snap (bbox = objeto); `--simplify` controla a
densidade no modo fiel. `--shadow remove` = histerese de borda por croma; `--shadow texture` =
subtrator de sombra por textura (corpo cinza-neutro, v0.5, com refino watershed v0.8); `--in2` =
fusão 2-fotos com luz oposta (v0.9; registro automático, sombras eliminadas, metal claro
recuperado); `--corner-radius`/`--shape` = priors de geometria declarada (v0.13, ver §Pipeline
5); `--symmetry` = espelho + média; `--humble` = contorno humilde (v0.12: cordas entre
trechos firmes quando a borda não tem apoio visual; `auto` só ativa em cena degradada, métricas
ganham `firme NN%` e, se houver, `flags N` + avisos por trecho incerto). **A cada
execução** sai, antes do `.svg`, o overlay PNG `_overlay_<nome>.png` (contorno em vermelho sobre
a foto retificada); `--inkscape` gera também `_overlay_<nome>.svg` editável. `--edit` abre o
**editor de nós** (GUI tkinter, `outline_editor.py`) entre a detecção e a saída: fundo renderizado
por **recorte do viewport** (custo independente do zoom); "Re-trace" traça a curva G1 pelos nós
(`cubics_through_nodes`); **WYSIWYG** — "Finalize" grava **EXATAMENTE a curva na tela** (literal,
sem recalcular nem snap). Além das ops de nó, expõe (011) Symmetry/Mirror (`mirror_contour`),
cota W×H (Size), Rotate (`rotate_nodes`), Pan (`translate_nodes`), Measure (`measure_snap`/
`nearest_measure` — medição em mm com trava de eixo, persistente até excluir), **move em
grupo** (`move_selection`: com nós selecionados via Shift+clique, um clique aplica a todos o Δ
do 1º selecionado) e **Align V/H** (`align_selection`, v0.16: 2+ selecionados alinham na
coordenada do 1º) — mecânica no §Testes E, operação no [manual](manual.md) §`--edit`.
**Rotate/Pan persistem**: ao Finalizar, o total acumulado vai p/ o sidecar
`<foto>.adjust.json` (`save_adjust`) e TODA execução seguinte o reaplica
(`load_adjust` → kwarg `adjust` de `generate_outline`: o giro roda foto+máscaras juntas pela
matriz única `adjust_rot_affine`, o pan translada o contorno extraído em mm exatos).
**Pins persistem (v0.15)**: nós que o usuário REPOSICIONA no editor (arrasto/move em grupo,
alça magenta) viram **pontos fixos** no mesmo sidecar; o replay (`apply_pins`) deforma a
silhueta extraída — e a `sil_ref` do gate — p/ passar EXATO por cada pin, com decaimento cos²
ao longo do arco (`PIN_FALLOFF_MM`), corrigindo a segmentação (ex.: sombra) na fonte em toda
execução; pins herdados abrem como nós magenta on-curve normais (v0.17, `snap_pins_to_nodes` encaixa/insere; botão-direito exclui).
**Segmentos fixos persistem (v0.18)**: hierarquia magenta (usuário, fixo) / amarelo
(calculado). Trecho com as DUAS pontas pinned é FIXO — derivado de `pinned`, sem marcação
extra — e vai p/ o mesmo sidecar (`segments`: pontas a/b, flag de reta e a cúbica DA TELA).
O replay costura a geometria salva na silhueta (`apply_segments`, depois dos pins; arco
escolhido por menor desvio, recusa com aviso acima de `SEG_SPLICE_DEV_MM`) e a emissão
substitui o arco da curva ajustada pelas cúbicas salvas LITERALMENTE
(`splice_fixed_cubics`, último passo de `_fit_for_output` — depois de simetria/snap/humble,
nada mais toca o trecho): no setor protegido o algoritmo não adiciona nó nem deforma nada;
as emendas do lado calculado são encaixadas exatas em a/b (G0 garantido, tangente
preservada por translação do handle). `--debug-dir` grava intermediários. Marcadores insuficientes →
aborta com mensagem clara. (Referência operacional completa das flags: [manual.md](manual.md); resumo em inglês no
[README.md](../README.md) §4.)

## Constantes (defaults, topo de `photo_to_outline.py`)

`PX_PER_MM = 8.0` (resolução do canvas) · `DICT_NAME = "DICT_4X4_50"` · `MIN_MARKERS = 8` ·
`TILT_WARN_DEG = 5.0` · `SEG_SAT_MARGIN = 45` / `SEG_VAL_FRAC = 0.30` (colorido OU escuro vs
fundo; default do `--val-frac`, suba p/ corpo cinza-neutro) · `SEG_VAL_WEAK_FRAC = 0.65` / `SEG_WEAK_SAT_MIN = 35` / `SEG_SHADOW_GROW_MM = 3.0`
(histerese do `--shadow remove`) · `SEG_TEX_WIN = 9` / `SEG_TEX_GAIN = 6.0` / `SEG_TEX_BG_FRAC = 0.93`
/ `SEG_TEX_BODY_FRAC = 0.80` / `SEG_TEX_LIGHT_FRAC = 0.70` (subtrator de sombra do `--shadow texture`:
janela da textura, Otsu adaptativo, corte de corpo, corte de sombra-clara) ·
`SEG_HUE_MARGIN = 25` / `SEG_HUE_SAT_MIN = 60` (matiz) ·
`SEG_WS_ERODE_MM = 2.0` / `SEG_WS_BAND_MM = 3.0` / `SEG_WS_FG_VAL_FRAC = 0.50` (marcadores do
refino watershed do `texture`, v0.8) ·
`FUSE_SEARCH_MM = 10.0` / `FUSE_ANGLE_DEG = 4` (registro da fusão 2-fotos) ·
`FUSE_MIN_LOBE_MM = 2.0` / `FUSE_ALIGN_MAX = 0.7` (direção de sombra por lóbulo; aviso de
sombras do mesmo lado) · `FUSE_FAINT_SAT_MARGIN = 10` / `FUSE_FAINT_VAL_MAX = 1.05` (predicado
faint-metal do modo 2 fotos) · `FUSE_GROW_MM = 0.0` (default do `--fuse-grow`) ·
`ILLUM_SCALE = 0.125` / `ILLUM_KERNEL_FRAC = 0.9` / `ILLUM_MAX_GAIN = 3.0` (flat-field) ·
`SYM_SEARCH_MM = 4.0` · `LEVEL_MIN_DEG = 0.2` / `LEVEL_MAX_DEG = 7.0` / `LEVEL_ASPECT_MIN = 1.05`
/ `LEVEL_LINE_MIN_MM = 8.0` (auto-nível `--level`, 011/F3: faixa fina da correção; guarda de peça
~quadrada/redonda + reta que a resgata) · `MIN_RADIUS_MM = 1.5` · `SMOOTH_MM = 8.0` · `CLEARANCE_MM = 0.0` (sem
ganho) · `ANCHOR_SIMPLIFY_MM = 2.0` (modo fiel) · `ANCHOR_EPS_MM = 0.08` (fiel)
· `POCKET_EPS_MM = 0.5` (penetração tolerada) · `ANCHOR_HANDLE_CAP = 0.40` (teto do handle =
fração da corda, anti-laço) · `ANCHOR_MIN_DIST_MM = 10.0` (densidade do pocket) ·
`PROTRUSION_DEV_MM = 0.8` (proeminência mín.) · `CONTAIN_COVERAGE = 0.99` (abaixo,
avisa) · `LINE_TOL_MM = 0.3` / `ARC_TOL_MM = 0.3` (primitivas v0.10; defaults de
`--line-tol`/`--arc-tol`, 0 desliga) · `LINE_MIN_MM = 5.0` / `ARC_MIN_MM = 2.5` (comprimentos
mínimos) · `ARC_R_MIN_MM = 0.8` / `ARC_R_MAX_MM = 60.0` (faixa de raio plausível; também veta
reta que é arco disfarçado) · `PRIM_TRIM_MM = 0.8` (recuo das pontas de reta → filete G1) ·
`CORNER_RADIUS_MM = 0.0` (prior de raio `--corner-radius`, v0.13; 0 desliga) ·
`PIN_FALLOFF_MM = 6.0` (meia-janela de arco da deformação de um pin do sidecar, v0.15) ·
`SEG_SPLICE_DEV_MM = 15.0` (desvio máx. p/ casar um arco com um segmento FIXO salvo, v0.18;
acima disso a costura é recusada com aviso — fallback v0.17, só pins) ·
`SHAPE_INFL_MAX_MM = 2.0` / `SHAPE_GAP_MM = 5.0` (salvaguardas do `--shape`: inflação e vão
máximos antes do fallback) ·
`FIT_TOL_MM = 0.2` · `BEZIER_GUIDE_MM = 0.5` · `CORNER_ANGLE_DEG = 40.0` ·
`RASTER_PPM = 16.0` · `OUTLINE_COLOR = "#ff00ff"` / `OUTLINE_FILL_OPACITY = 0.25` ·
`HUMBLE_MIN_FIRM_FRAC = 0.5` (gatilho do `--humble auto`) / `HUMBLE_GRAD_WIN_MM = 0.5` (janela
de firmeza) / `HUMBLE_SLIVER_TEX_FRAC = 0.03` / `HUMBLE_SLIVER_MIN_MM2 = 4.0` (guarda de lisura
do descarte) / `HUMBLE_MIN_GAP_MM = 10.0` (piso da subdivisão → keep+flag) /
`HUMBLE_FIRM_CLOSE_MM = 1.0` / `HUMBLE_FIRM_ISLAND_MM = 2.0` (limpeza da classificação) /
`HUMBLE_CHORD_STEP_MM = 1.0` (densificação) / `HUMBLE_GRAD_FLOOR = 8.0` /
`HUMBLE_GRAD_CAP = 3.0` (piso e teto do limiar de firmeza — contorno humilde, v0.12).

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
translúcido. Sem referência desenhada à mão. **Contorno humilde como fallback, não
sempre-ativo (v0.12):** diante de borda sem contraste, a decisão de projeto foi **admitir a
incerteza** em vez de perseguir a segmentação perfeita — o pacote "esperto" avaliado na v0.11
(registro por ZNCC de gradiente, faint-metal adaptativo, watershed com guardas) foi
**rejeitado** pelo usuário por complexidade/risco; no lugar, cordas entre trechos firmes +
flags honestos, ativados **só** quando a cena degrada (fotos boas ficam byte-idênticas, por
teste). Quando ativa, o `contém` mede contra a silhueta **pós-humilde**: a pré-humilde é
sabidamente errada nos vãos incertos (medir contra ela puniria exatamente o conserto) — a
honestidade vai p/ os flags, não p/ o gate. **Objetivo:** alimentar **gridfinity
personalizável** a partir do contorno medido.

## Testes

`tests/test_photo_to_outline.py` + `tests/test_calibration_target.py` +
`tests/test_outline_editor.py` (`unittest`, via `run_image_tests.py`).
**Contagem canônica: 264/264 verde** (única fonte; os guias só dizem "verde"). Níveis:

- **A. Unidade (puro):** `polygon_area`/`ensure_ccw` (sinal, CCW); `douglas_peucker` (reduz
  vértices, preserva bbox); `chaikin` (baixa o ângulo máx.); `enforce_min_radius`
  (`min_corner_radius ≥ r_min`); `px_per_mm`; `homography_from_corners`+`apply_homography`
  (recupera 4 cantos); `coverage`/`boundary_roughness`; **Bézier** (`fit_closed_beziers` fita
  círculo em poucas cúbicas; `_corner_indices` acha 4 cantos). `TestAnchoredFit`: todos os nós
  G1; o **POCKET** ancora 1 extremidade/quadrante quando `min_dist` é grande, a densidade emerge
  só do `min_dist` (estrela: menor distância ⇒ mais cúbicas; **sem teto de nós** — `MAX_NODES`
  não existe mais) e **contém a peça** (coverage ~1) em convexa e côncava.
  `TestProtrusionAnchors`: saliência no meio de aresta ganha âncora, o pocket a alcança, círculo
  **não** gera âncora espúria, nó G1. `TestCoverageTolerance` (v0.7): `coverage(tol_mm=)` perdoa
  penetração rasa e mantém corte profundo. `TestPreserveSpikes` (v0.7): espigão fino restaurado
  (ponta crua), forma lisa intacta, pocket alcança a ponta. `TestPrimitiveFit` (v0.10): retângulo
  arredondado → exatamente 4 retas eixo-alinhadas + 4 arcos com r≈r do canto; círculo não vira
  polígono (veto por círculo) e sim arcos de raio certo; aresta emitida é reta de verdade
  (spread < 0.08 mm) e **nunca corta a peça** (reta-suporte externa); menos nós que o legado;
  todo nó G1; `line_tol_mm=0` reproduz o legado; kwargs com default em toda a cadeia
  (`generate_outline`, `polygon_to_svg`, `fit_closed_beziers_anchored`, `fit_anchored_cached`).
  `TestGeometryPriors` (v0.13): prior `--corner-radius` cola os arcos no raio declarado
  (cantos 4.6 + prior 5 → raio exatamente 5; fora da janela NÃO cola; fit completo emite canto
  r≈5 contendo a peça); `--shape rect` → exatamente 8 cúbicas com tamanho colado e raio exato,
  recupera rotação 3° + ruído (área ≈ ideal), canto vivo declarado vira `MIN_RADIUS_MM`,
  círculo "descrito" como retângulo → WARNING + fallback genérico (ainda contém), `--faithful`
  ignora o shape; priors com default em toda a cadeia.
  `TestAutoLevel` (011/F3): tabela do `snap90`; o estimador recupera os ângulos injetados
  (retângulos girados — a tabela do experimento virou caso de teste); disco é recusado
  (envelope instável), quadrado com arestas passa; correção fecha o laço com **resíduo < 0.3°**
  (nível B sintético); guardas da faixa (`LEVEL_MIN` intacto por identidade de objeto,
  `LEVEL_MAX` warn sem girar).
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
  `TestWatershedEdgeRefine` (v0.8): na cena com UMBRA lisa-e-escura + ruído de foto (seed fixa),
  o refino **avança a borda ≥ 2 mm p/ dentro** da umbra que o corte de valor mantinha, **sem
  comer o corpo** (mediana por linha — a corrida de inundação é irregular no ruído); a guarda
  sem-marcador-FG devolve a máscara intacta.
- **B5. Fusão 2-fotos (`TestFuseMasks` + `TestFaintMetal`, v0.9):** máscaras sintéticas de peça
  em L (assimétrica). Idênticas → passa direto (rot 0, shift 0); sombras **opostas** coladas na
  peça → as DUAS caem e a peça fica (e o lóbulo maior identifica a foto de pior luz p/ o
  overlay); peça **girada 180° e deslocada** → o registro recupera rot+shift (IoU ≥ 0,97 com a
  máscara 1). `TestFaintMetal`: o predicado (só do modo 2 fotos) recupera o "conector" claro
  (S = fundo+18, V = papel) que o default não vê.
- **B4. Regularização da silhueta (`TestRegularizeSilhouette`):** remove serrilha mantendo a área e
  o tamanho macro; `preserve_convex=True` (`--mask-smooth-keep-bumps`) **preserva o ressalto
  convexo** que o modo isotrópico arredonda, ainda preenchendo a reentrância côncava; **avisa**
  (v0.7) quando remove saliência convexa relevante (espigão 1×5 mm) e fica calado p/ serrilha
  sub-limiar ou quando o keep-bumps a preserva.
- **B6. Contorno humilde (`TestHumbleRewrite`, v0.12):** fixtures sintéticas em memória
  (retângulo + "foto" cinza com degrau desenhado; halos = meia-elipses SEM degrau; textura =
  xadrez). Borda 100% firme → **no-op** (mesmo objeto de máscara, 0 cordas/flags, `auto` não
  dispara); bojo liso → **corda** (desvio ≤ 1 mm da aresta verdadeira, sem cortar a peça);
  3 halos → **gatilho `auto` dispara** sozinho (fração firme < 0.5); bojo com textura →
  corda rejeitada, subdivisão confina, **nenhum ponto entra > 1.5 mm** na peça verdadeira;
  vão pequeno texturizado → **keep + flag** (posição/extensão certas, máscara intacta);
  **merge 2b** derruba a "tenda" (menos cordas E menos área falsa que `merge=False`); foto
  sem degrau nenhum → 0% firme, original mantido + nota; kwargs com default em toda a cadeia;
  **regressão thermpro**: `--humble auto` = saída idêntica a `off` (firme ~92%, dormente);
  `--humble on` + `--faithful` → aviso e ignorado (`auto`+`faithful` ignora em silêncio).
- **C. Ponta-a-ponta (`thermpro.jpg`, skip se ausente — `TestEndToEndThermpro`):** 32/32
  marcadores; escala plausível; no **modo fiel** a peça cabe (`coverage ≥ 0,99`), linha
  limpa, **bbox do SVG = dimensão medida**; no **default (POCKET, `min-dist` 10)** o pocket
  **contém** a peça (`coverage ≥ 0,99`) ficando ≥ objeto; `min_corner_radius` (sem bicos); contorno único
  fechado, poucos nós. `TestSilhouetteRef` (v0.7): `return_silhouettes=True` devolve a silhueta
  de referência pré `--mask-smooth-mm` (mais serrilhada, ~mesma área). **`--level auto` no
  thermpro = saída idêntica ao baseline** (estimador dá ~0° → abaixo de `LEVEL_MIN_DEG` →
  regressão de "não mexer no que está nivelado", 011/F3).
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
  `mm_to_px`/`px_to_mm` ida-e-volta. `TestStraightSegments` (v0.10): `straighten_between` remove
  os nós interiores do caminho MAIS CURTO entre 2 nós e marca o trecho RETO; retas existentes são
  remapeadas (`remap_lines_insert`/`remap_lines_delete`: inserir divide em 2 retas, excluir funde
  — reto só se ambos); `cubics_through_nodes(line_segs=)` emite a reta NA corda, vizinho sai
  tangente (G1), duas retas consecutivas = canto legítimo, e o índice sobrevive à inversão CCW.
  **Simetria (011/F1):** `mirror_index`/`sym_check_pairing` (aceita a saída REAL de
  `symmetrize_beziers`, rejeita edição livre/eixo errado); ops-par (`move_node_sym`/
  `insert_node_sym`/`delete_node_sym`/`straighten_between_sym`) **preservam o invariante
  `i↔(N−i)%N`** inclusive em sequência (inserir→mover→excluir) e re-canonicalizam quando a
  exclusão do nó de eixo desloca o pareamento; nó de eixo travado em `x=c`. **Mirror (F1b,
  `mirror_contour`):** constrói pareamento válido a partir de contorno ARBITRÁRIO com nós de
  emenda na interseção exata; recusa >2 cruzamentos; eixo movido + `snap_seam_nodes` não deixa
  degrau na emenda; retas do lado-mestre sobrevivem espelhadas; eixo horizontal idem.
  **Rotação (F4, `rotate_nodes`):** preserva distâncias/área, centro fixo, ida-e-volta.
  **Pan (`translate_nodes`):** translação pura preserva a forma e o pareamento sobrevive com o
  eixo deslocado do MESMO dx (é o que permite o modo Pan não desligar a simetria).
  **Move em grupo (`TestMoveSelection`):** `move_selection` leva o 1º selecionado ao alvo e
  aplica o MESMO Δ aos demais (1 nó = teleporte; seleção vazia = cópia; índices com wrap).
  **Pins (`TestPinnedTracking`, v0.15/v0.17):** `remap_pinned` preserva as marcas de nó através
  de ops ESTRUTURAIS por posição (insert desloca, delete desafixa, straighten sobrevive, wrap);
  `snap_pins_to_nodes` (v0.17) converte os pins HERDADOS do sidecar em nós on-curve na abertura
  (encaixa no nó a ≤ `PIN_SNAP_TOL_MM` ou insere um novo; empty = no-op; degenerado = append).
  **Align (`TestAlignSelection`, v0.16):** `align_selection` alinha 2+ selecionados na
  vertical/horizontal na coordenada do 1º selecionado (outra coordenada preservada; < 2 =
  cópia no-op; wrap).
  **Measure (`TestMeasureTool`):** `measure_snap` trava o 2º ponto no eixo dominante (|dx|≥|dy|
  → horizontal, empate incluso; `free=True`/Ctrl mantém livre); `measure_length`/
  `measure_midpoint`; `nearest_measure` mede a distância ao SEGMENTO (hit-test do excluir).
  **Segmentos fixos (`TestFixedSegmentsEditor`, v0.18):** `fixed_segment_indices` deriva o
  status (duas pontas pinned, wrap incluso); `export_fixed_segments` exporta a cúbica DA TELA
  orientada a→b mesmo com a inversão CCW do re-traçar e pula trechos não fixos;
  `lines_from_segments` restaura o flag de reta herdado (qualquer orientação; pontas não
  adjacentes ignoradas); `pin_inserted_nodes` faz o nó inserido DENTRO de trecho fixo nascer
  pin (e só nele); `toggle_pin` alterna a marca de fixo de um nó (double-clique na view,
  wrap de índice incluso) sem movê-lo.
  A view tkinter é glue fino e **não** é instanciada (runner
  headless); o Finalizar grava EXATAMENTE a curva exibida (WYSIWYG), a foto com o giro
  da sessão e o ajuste TOTAL (rot/pan + pins mesclados) p/ o sidecar, sem recalcular.
- **F. Saída/CLI (`TestOutputFitSourceOfTruth`, `TestSvgNameEscaping`, `TestCliDictValidation`,
  `TestMakeTargetCli`).** `_fit_for_output` é a **fonte única** do ajuste emitido (.svg final,
  overlay Inkscape e métricas — o overlay recebe a MESMA `--symmetry`; snap de bbox só no modo
  fiel); o `name` (arquivo/`--name`) entra **escapado** no SVG (nome hostil não injeta markup nem
  quebra o XML); `--dict` restrito às `choices` da tabela `DICT_CAPACITY` nos dois CLIs e
  `target_layout` levanta `ValueError` p/ dicionário desconhecido. `TestManualAdjust` (ajuste
  persistente): roundtrip do sidecar `save_adjust`/`load_adjust`, zerado REMOVE o arquivo,
  corrompido é ignorado com aviso, `adjust_rot_affine` reproduz exatamente a rotação dos nós
  em mm (anisotropia incluída; 0° = identidade) e o replay do pan translada a silhueta do
  thermpro EXATAMENTE (sub-pixel, e2e). `TestPins` (v0.15): `apply_pins` passa EXATO pelo
  pin (vértice mais próximo), decai em cos² ao longo do arco (peso 0.5 na meia-janela) e não
  toca fora da janela; dois pins somam; sidecar SÓ com pins é efetivo (mantém o arquivo) e o
  sidecar legado (sem a chave) lê `pins=[]`; e2e no thermpro: o replay deforma a silhueta
  localmente (passa pelo pin, lado oposto intacto). `TestFixedSegments` (v0.18): roundtrip do
  sidecar com `segments` (SÓ segments mantém o arquivo; legado lê `segments=[]`; zerar tudo
  remove); `apply_segments` substitui o arco certo pela geometria salva (calombo removido,
  pontas exatas, lado oposto intacto, silhueta CW inclusive) e RECUSA com aviso o segmento
  cujo desvio passa de `SEG_SPLICE_DEV_MM`; `splice_fixed_cubics` emite as cúbicas salvas
  bit a bit (nó interior do arco substituído some, caminho segue fechado/encadeado);
  `_fit_for_output(segments=)` protege o arco (nenhum nó novo dentro dele, cúbica literal na
  saída); e2e no thermpro: o replay do segmento reto vira corda exata na silhueta, lado
  oposto intacto. `TestCubicRoots`: raiz DUPLA
  achada apesar do arredondamento float (tolerância relativa no `det`; antes `det == 0` exato
  perdia a raiz e um cruzamento tangente do eixo sumia). Robustez do layout: borda que não
  comporta 2 marcadores com o vão mínimo recebe **1 centrado** (nunca um par quase-sobreposto)
  e página pequena demais (miolo degenerado) levanta `ValueError`. `estimate_tilt_deg` recebe a
  homografia mm→imagem PRONTA (o inverso da que `rectify` já resolveu — sem 2º RANSAC).
  `TestEditFlowGuards`: `--edit` com detecção degenerada (cub0 vazio) aborta com erro ANTES de
  abrir o editor; editor devolvendo lista vazia não grava nada (antes: crash em `min()` de
  bbox vazia ao Finalizar); e o `contém` impresso pelo `--edit` é medido contra a silhueta de
  **referência** (`return_edit_data` devolve `sil_ref`) com `CONTAIN_TOL_MM` — o MESMO gate
  honesto (v0.7) do fluxo padrão, não mais contra a silhueta pós `--mask-smooth-mm` sem tolerância. `TestSymmetrizeBeziers`: 2 cruzamentos do eixo → espelhado, fechado
  e simétrico; **>2 cruzamentos** (côncava através do eixo: 2+ arcos no lado mantido, cada
  arco+espelho = laço separado) → **fallback com aviso**, contorno original intacto (antes só o
  1º arco sobrevivia e o resto era descartado em silêncio).
