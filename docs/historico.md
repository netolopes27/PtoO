# 17 — Foto → contorno (SVG em mm a partir de foto) · Spec 12

**Data:** 2026-06-23 · **Spec:** [`specs/12-foto-para-contorno.md`](../specs/12-foto-para-contorno.md) · TDD-first.

## O quê

Tooling novo `tools/photo_to_outline.py`: recebe uma **foto** de uma ferramenta sobre base quadriculada
(quadrado = 10 mm) e emite um **SVG em mm** (fundo branco, contorno preto) com o contorno **externo** da peça,
corrigido de escala/ângulo pela grade e **suavizado para impressão 3D** (sem cantos de 90°, bico arredondado).
A saída alimenta `tools/svg_to_scad.py` → `ItemPoly` → `gridfinity_itemholder` (Spec 11), automatizando a
primeira metade do fluxo (antes desenhada à mão no Inkscape).

## Por quê

A pedido do usuário: criar caixas custom a partir de uma **foto** da ferramenta, não de um traçado manual.
Fecha o gargalo do front-end do item holder (foto → contorno em mm pronto p/ o pipeline existente).

## Decisões

- **Stack:** `numpy` + `opencv-python` em **venv isolado** `tools/.venv/` (decisão do usuário; pip já instalado).
  A suíte OpenSCAD (`tests/run_tests.py`) segue **stdlib-pura** — só este tooling de visão depende de pip.
  Verificado: há wheel `abi3` do `opencv-python` que cobre Python 3.14 (o risco do plano não se concretizou; sem
  fallback Pillow/scipy). `tools/requirements.txt` + `.gitignore` (venv, `_debug/`, `__pycache__`).
- **Calibração automática pela grade** via **autocorrelação do perfil de bordas** (Sobel→projeção→autocorr, com
  pico sub-pixel), e **não** clustering de linhas Hough: robusto à oclusão da ferramenta (a periodicidade da grade
  domina o perfil mesmo com parte das linhas coberta). Confiança explícita aborta (`GridDetectionError`) em vez de
  emitir escala errada. Deskew por rotação (mediana do ângulo das horizontais Hough).
- **Suavização p/ impressão** (refinada a pedido do usuário — prioridade: **linha limpa + encaixe garantido**,
  o SVG é insumo de impressão): `enforce_min_radius` (filete por **abertura+fechamento morfológico** com disco
  `r_min`, *garante* curvatura ≥ r_min em todo canto convexo, incl. o bico; + dilatação `--clearance`) →
  **low-pass forte** `lowpass_closed(--smooth-mm, default 8 mm)` que elimina o **serrilhado** de alta frequência
  herdado da foto (~0,22 mm/px), preservando features reais (≫ 8 mm) → decimação `approxPolyDP` (eps 0,02 mm) p/
  ~250 pontos. **Encaixe garantido por construção:** `--clearance` (default 0,8 mm) ≥ recuo do low-pass ⇒
  `pocket ⊇ ferramenta` (a peça cabe), verificado por `coverage`. Métricas novas: `coverage` (encaixe) e
  `boundary_roughness` (aspereza/limpeza da linha).
- **Medição de raio sem viés:** `min_corner_radius` usa circunraio com vizinhos afastados ~`window` mm (não os
  imediatos — estes subestimam ~28% num contorno discretizado). Ripple de rasterização removido por **low-pass de
  Hann** no domínio das coordenadas (`lowpass_closed`), preservando a curvatura macro garantida pela morfologia.
- **IoU alinhado pelo centro** de bbox (formas finas/alongadas: deslocamento pequeno derruba o IoU).

## Arquivos

- **Novos:** `tools/photo_to_outline.py`, `tools/requirements.txt`, `tools/tests/test_photo_to_outline.py`,
  `tools/tests/run_image_tests.py`, `specs/12-foto-para-contorno.md`, este progresso.
- **Tocados:** `.gitignore` (venv/_debug/__pycache__).
- **Saída/entrada do usuário:** `tools/serra.JPG` (foto) → `tools/serra.svg` (gerado, direto do JPG).
- **Também tocado:** `Manual.html` (subseção "Do JPG ao contorno").

## Resultado / verificação (estado atual)

- **Suíte de imagem 33/33 verde:** `tools/.venv/Scripts/python tools/tests/run_image_tests.py` (unidade +
  sintético + ponta-a-ponta). Roda **separada** da suíte OpenSCAD (esta é stdlib-pura).
- **Ponta-a-ponta direto do `serra.JPG`** (sem referência à mão): escala da grade **por eixo** (regressão
  sub-pixel) com **período = quadrado + linha (10+1 mm)** → objeto **235,95 × 40,72 mm** (≈ régua do usuário); SVG
  sai **nessa dimensão exata** (snap); **encaixe 0,9999**; linha limpa; **55 Béziers**; contorno único fechado.
- **Cadeia validada:** `serra.svg` → `svg_to_scad.py` → `serra_points.scad` → `ItemPoly` rende **manifold** no
  OpenSCAD.
- Histórico dos refinos (serrilhado → Béziers → mínimo por contenção → reinício limpo → escala correta) abaixo.

## Refino 2 — fundo + curvas de Bézier (2026-06-23, a pedido do usuário)

- **Fundo removido:** o SVG passa a emitir **só o contorno** (`<path fill:none>`), sem o `<rect>` branco — o
  branco era só p/ visualização do usuário; o insumo de impressão é o contorno.
- **Saída em Béziers cúbicas (Schneider) em vez de polyline.** O usuário editou à mão (`serra_polido.svg`) trocando
  as curvas da lâmina por Béziers com poucos nós. Comparação mine×polido (renderização preenchida com cores de
  destaque + XOR): formas idênticas (XOR ≈ 2,9%), e a edição dele era de **representação** — Béziers que *passam
  pela média* do traço, menos inflexões de curvatura. Formalizado: `fit_closed_beziers` (detecção de cantos por
  ângulo com NMS circular + ajuste por mínimos quadrados recursivo, split no ponto de maior erro). O `polygon_to_svg`
  emite comandos `C`; `--fit-tol`/`--polyline` controlam. **Resultado:** `serra.svg` saiu de 245 retas → **48
  Béziers**; aspereza 0,055→**0,033** (mais limpo que o polido, 0,066); inflexões 64→**40** (polido 43); encaixe
  mantido (cobertura 1,0); diferença p/ o polido ≈ 2,9% de área. Cadeia OpenSCAD intacta (svg_to_scad achata os
  `C`; `ItemPoly` rende manifold). Suíte 22→**32** (testes de Bézier/canto/coverage/roughness).

## Refino 3 — mínimo de Béziers por contenção (2026-06-23, a pedido do usuário)

Nova regra do usuário: **o traçado só pode ser Béziers, na MENOR quantidade possível, com a única restrição de o
objeto caber na cavidade**. Reframe: dividir uma curva não por tolerância, mas só quando ela invadiria a peça.

- **`fit_closed_beziers_contained`**: varre tolerâncias de Schneider grande→pequena e fica com a **maior** cuja
  curva **não penetra** a silhueta+`c_fit` além de `eps` (penetração medida por `distanceTransform` —
  `_floor_field`/`_max_penetration`). Tolerância grande = menos nós.
- **Descoberta:** uma recursão "one-sided" por contenção pura **estufa para fora** (cúbica sem limite externo →
  barrigas, altura 38,8→42 mm). O ajuste por **tolerância** é bem-comportado (rastreia o guia, não estufa) — então
  o mínimo se obtém variando a tolerância, não trocando o algoritmo.
- **Orçamento de suavização `--guide`** (folga do guia de forma) é o trade-off real: guia 0,8→48 curvas; 1,0→37;
  **1,2→17** (encaixe 1,0, sem barriga). O piso de contenção é a peça crua (`c_fit=0`): o SVG é o traço mínimo
  encostando na peça; a folga de impressão entra **a jusante** no `gridfinity_itemholder` (`clearance`).
- **Resultado:** `serra.svg` = **17 Béziers** (era 48), encaixe (cobertura) **1,0**, linha lisa (some o serrilhado
  da base), forma fiel. Cadeia OpenSCAD mais leve (17×24=408 pts vs 1152). CLI: `--guide` (menos curvas/mais folga),
  `--c-fit` (folga embutida), `--tol-fit` (modo tolerância fixa). Suíte 32→**33**.

## Refino 4 — reinício limpo do JPG + doc no manual (2026-06-23, a pedido do usuário)

- **Removidas as referências desenhadas à mão** (`test_serra.svg`, `serra_polido.svg`) e o `serra.svg` antigo:
  eram muleta de calibração/teste e induziam viés ("a silhueta já não correspondia à foto"). Verificado por overlay
  que o contorno é tirado **direto do JPG** e bate com a foto (deskew 0°, escala 44,7 px = 10 mm). Removidas também
  as funções-muleta `read_svg_polygon_mm`, `polygon_iou`, `rasterize`, `_center_in_canvas`.
- **Testes ponta-a-ponta refeitos** sem referência: escala validada pela **grade** (faixa física plausível
  180–240 × 25–55 mm), e encaixe/limpeza/curvas medidos contra a **silhueta do JPG**. Suíte 33→**32** verde.
- **Pipeline reiniciado:** `serra.svg` regenerado direto do JPG (17 Béziers, encaixe 1,0). Usuário aprovou o
  resultado e aplicou a folga **escalando o SVG em +0,6 %**.
- **Doc:** subseção "Do JPG ao contorno" no `Manual.html` (pipeline foto→SVG→`ItemPoly` + a **observação da folga**:
  escalar o SVG, ou `clearance` do `gridfinity_itemholder`, ou `--c-fit`; e o trade-off `--guide`).

## Refino 5 — escala correta pela grade (2026-06-23, a pedido do usuário)

Usuário: "o tamanho da serra ainda está errado; **antes do contorno, extraia as dimensões do objeto pelos
quadrados** (10 mm cada). Primeira coisa a fazer." Dois erros de escala encontrados e corrigidos:

- **Autocorrelação imprecisa** (44,70 px) vs **regressão de treliça** (44,43 px, usando as 23 linhas boas numa base
  longa) — ~0,6% de erro na largura. Troquei o detector por `_edge_profile_peaks` + `_lattice_spacing` (regressão
  `pos = passo·índice + b`, robusta a linhas espúrias da ferramenta; autocorrelação vira só o chute inicial).
- **Anisotropia ignorada:** X = 44,43 px/10 mm, **Y = 45,38 px/10 mm** (~2%; foto não perfeitamente perpendicular).
  `rectify` passou a medir e devolver escala **por eixo** (`mm_per_px_x`, `mm_per_px_y`); `extract_outline` aplica
  cada uma → corrige largura E altura. Objeto medido: **214,5 × 37,0 mm** (antes 214,1 × 37,8 — errado nos 2 eixos).
- **Tamanho do SVG fixado no objeto:** `_scale_cubics_to_bbox` faz "snap" da bbox da saída (por eixo) na dimensão
  medida → o SVG tem o **tamanho real**, não o inflado pelo orçamento de suavização. Essencial p/ o fluxo do usuário
  (folga aplicada escalando o SVG +0,6 %).
- **Resultado:** `serra.svg` = 49 Béziers, dimensão **214,50 × 37,02 mm = medida da grade**, encaixe 0,9999, linha
  limpa. Suíte **33** verde (+`_lattice_spacing` sub-pixel, +escala por eixo, +SVG-bbox=objeto). Reportar a
  dimensão do objeto virou o 1º passo impresso pelo CLI.

## Refino 6 — espessura da linha no período da grade (2026-06-23, a pedido do usuário)

Usuário mediu a serra com régua: **~235 mm**, mas o pipeline dava 214,5 (~9% menor). Causa apontada por ele: a
**linha da grade tem 1 mm** e eu não considerava. Confirmado: o espaçamento detectado (44,4 px) é o **período
linha-a-linha**, que vale **quadrado claro (10 mm) + linha (1 mm) = 11 mm**, não 10. Tratar como 10 mm
subdimensionava `line/período ≈ 1/11 ≈ 9%`.

- **Correção:** `rectify(grid_mm, line_mm)` usa `período_mm = grid_mm + line_mm` na escala (por eixo). `LINE_MM=1.0`
  default (a base do usuário); CLI `--line-mm`. Medição de espessura na foto confirmou linha ~0,9–1,0 mm.
- **Resultado:** objeto = **235,95 × 40,72 mm** (≈ os 235 mm medidos com régua). `serra.svg` regenerado nessa escala
  (55 Béziers, encaixe 0,9999). Suíte 33→**34** (+`test_line_thickness_scales_period`; sintético usa `line_mm=0`).

## Refino 7 — fluxo travado (etapa 1 sem ganho) + traçado ancorado nas extremidades (2026-06-23, a pedido do usuário)

Dois pedidos do usuário após a escala correta:

1. **Definir o fluxo e travar a etapa 1 sem ganho.** Fluxo: `serra.JPG → photo_to_outline.py → serra.svg (tamanho
   REAL)` → depois `svg_to_scad.py` (conversão pura, sem offset) → `gridfinity_itemholder(..., clearance=X)` que
   aplica a folga via `offset()` ([module_item_holder.scad:14](../modules/module_item_holder.scad:14)), **ou** o
   usuário escala/edita à mão. Para não acumular ganho, **`CLEARANCE_MM` foi a 0** (era 0,8): o contorno sai no
   tamanho real puro; a folga é 100% a jusante. Documentado no `Manual.html` e na spec.

2. **Menos pontos, mais justo (mantendo "tem que caber").** Diagnóstico via probes: o serrilhado já estava mínimo
   (~0,03 mm); as "irregularidades" eram (a) a **borda inferior ruidosa** da segmentação que o ajuste por tolerância
   uniforme seguia, gastando nós em todo o contorno, e (b) o estufamento p/ fora. Tabela penetração×tolerância
   mostrou a tensão física: 13 nós penetram 1,6 mm (não cabe) vs 52 nós penetram 0,29 mm.
   - **Algoritmo novo (ideia do usuário): ancorar nas EXTREMIDADES.** `fit_closed_beziers_anchored`: denoisa a
     silhueta (low-pass), fixa âncoras nos **vértices dominantes do fecho convexo** (`hull_anchor_indices` =
     `convexHull` + `douglas_peucker_idx`) e, **entre âncoras**, ajusta cúbicas **contidas** (`_fit_segment_contained`,
     maior tolerância sem penetrar > `eps`). Ancorar nos pontos mais distantes **garante caber** (a cavidade alcança
     bico/calcanhar/cantos) e dá transições suaves (fácil de imprimir, sem viradas bruscas). Vira o **modo padrão**;
     `--tol-fit` mantém o antigo, `--polyline` o cru.
   - **Knob `--simplify`** (RDP do fecho): trade-off nº de nós × justeza (maior = menos nós/mais "hull"; menor =
     mais justo). Default `ANCHOR_SIMPLIFY_MM = 2.0`.
   - **Resultado:** `serra.svg` = **31 Béziers** (era 55), 235,95 × 40,72 mm (tamanho real, sem ganho), encaixe
     0,996, linha limpa, bordas arredondadas. Round-trip por `svg_to_scad.py` ok (footprint 235,96 × 40,72).
     Overlay conferido visualmente (`_debug/serra_final.png`). Suíte **34→38** (+`TestAnchoredFit`: RDP-idx, âncoras,
     contenção+poucos nós, monotonicidade do `--simplify`; ponta-a-ponta repontado p/ o contorno ancorado emitido).
   - **Tensão inerente registrada:** sob "tem que caber", curva suave com poucos nós precisa estufar nas
     concavidades; o ruído sub-mm de segmentação é denoisado (o tool real fica contido; a folga a jusante cobre o
     resíduo). Recursão por contenção pura foi testada e **descartada** (corre/estufa demais).

## Ciclo novo — objeto trocado p/ thermpro; dividido em etapas (2026-06-24)

Usuário trocou a peça: **serra → ThermoPro** (`tools/thermpro.JPG`), sobre grade **branca/cinza de 30 mm** (linha
preta de 1 mm) em vez da base verde de 10 mm. Serra e derivados removidos. Rodar o pipeline antigo na foto nova
**degenerou**: a segmentação por "fundo verde" não acha verde → máscara = quadro inteiro → contorno = a foto toda
(travou em `process_for_print`, 6,5 GB). Diagnóstico ⇒ **dois consertos** (segmentação e retificação), atacados em
etapas avaliáveis pelo usuário. **Por quê em etapas:** o usuário pediu "tratar a foto e depois o contorno".

### Etapa A — retificação por HOMOGRAFIA da grade (perspectiva + inclinação) ✅
- **Antes:** `rectify` só rotacionava (deskew) e media escala por autocorrelação (`_detect_grid`, teto de período
  ~250 px). Na `thermpro.JPG` (poucos quadrados GRANDES, ~400 px) a autocorrelação travava num harmônico (~11 px) →
  escala absurda (mm/px 2,66 → objeto de "4 m"). O helper `homography_from_corners` existia mas era **ocioso**.
- **Agora (TDD-first):** detector de grade **por LINHAS** (não autocorrelação): `_grid_lines_mask` binariza (Otsu),
  **remove a pegada do objeto** (blob escuro fechado+dilatado — senão display/placa viram linhas espúrias) e roda
  **Hough na máscara limpa** (`_hough_on_mask`, `maxLineGap` grande ponteia o corte do objeto). Agrupa em 2 famílias
  (`_cluster_grid_lines`, TLS por linha), filtra fora-da-treliça (`_lattice_filter`), mede espaçamento pelo passo
  mediano (robusto a quadrado grande/pequeno). `homography_from_grid` (RANSAC sobre **todos os nós**) leva a grade a
  uma treliça ideal quadrada → **perspectiva + inclinação corrigidas**, escala **UNIFORME**. `_warp_to_canvas`
  ajusta a tela (cap de 3× p/ não explodir memória). Autocorrelação + deskew por rotação viraram **fallback**.
- **Bug pego e corrigido:** convenção de sinal do offset invertia o índice 0 → saída **rotacionada 180°** (H 2×2 ≈
  `diag(-1,-1)`). Normal reorientada p/ índice 0 = topo/esquerda → H ≈ +identidade.
- **Resultado (`thermpro.JPG`):** 4×4 linhas, grade **quadrada** (404,8 × 403,5 px), conf 0,99, mm/px **uniforme**
  0,0742, campo 117×107 mm; foto retificada reta e **na orientação certa** (conferida em `_debug/A_rectified_homog.png`).
- **Validação métrica (ideia do usuário):** medir um quadrado conhecido em CADA quadrante da foto retificada — todos
  têm que dar 30 mm; se variassem, a perspectiva não teria sido removida. `measure_grid_squares(gray, mmpp_x, mmpp_y)`
  mede cada quadrado linha-a-linha. **Resultado na `thermpro.JPG`:** X = 29,93/29,94/30,19 mm, Y = 29,96/30,05/30,01
  mm (média 30,0; desvio ≤ 0,12; erro ≤ 0,6%), largura da linha ≈ 1,04 mm (alvo 1,0). **Uniforme em todos os
  quadrantes ⇒ perspectiva removida, dimensão do objeto confiável.**
- **Testes:** `TestGridLineGeometry` (reta/interseção/TLS/índices), `TestRectifyPerspective` (keystone → grade volta
  a quadrada + quadrados de 30 mm uniformes em todo quadrante), `TestThermproGridMetric` (foto real, skip se ausente:
  escala uniforme + todo quadrado = 30 mm sem perspectiva residual). Suíte **38→47** (7 skip = ponta-a-ponta da
  serra, sai na Etapa B).

### Etapa B.0 — novo alvo de calibração impresso (moldura ArUco + centro branco) ✅
- **Por quê (decisão do usuário):** ele imprimiu a grade `quadro.svg` (A4, período 29,187 mm, linha 0,5 mm, gerada
  por tiled-clones do Inkscape) e perguntou se eu teria uma base **melhor** — já que **eu** gero a base E o detector,
  dá p/ co-projetar. A grade funciona (validada a 30 mm ± 0,2) mas é **anônima** (orientação ambígua — origem do bug
  de 180°), casada por **linha grossa** (Hough sub-px) e, pior, **linha preta confundível com a borda preta do
  objeto** — exatamente o que travaria a segmentação. Apresentei 3 opções; usuário escolheu a **Opção B (moldura de
  marcadores + miolo branco)**, pedindo **margem branca** (impressão sem sangria) e salvar como **`base.svg`** (não
  sobrescrever `quadro.svg`).
- **O ganho central:** o objeto fica no **miolo branco**, **sem nenhuma linha** sob ele → segmentação da Etapa B
  vira trivial (objeto sobre branco) **por design físico**, não por esperteza de algoritmo. Marcadores ArUco dão
  **ID único** (orientação inequívoca, robusto a oclusão) e cantos **sub-pixel** via `cv2.aruco` **nativo** (OpenCV
  4.13 no venv — **sem dependência nova**). O `tool` gera a própria base ⇒ *o impresso == o que o detector assume*.
- **Implementação (TDD-first):** `tools/calibration_target.py` (PURO, sem OpenCV — fonte única do layout, importável
  pelo detector da Etapa B): `target_layout()` → moldura de **uma espessura** com IDs sequenciais, `inner_rect` =
  miolo branco, `Marker.corners_mm()` na ordem ArUco, `homography_correspondences()` = contrato detector↔mm.
  `tools/make_calibration_target.py` renderiza o SVG (marcadores como retângulos **vetoriais** run-length, fundo
  branco + margem, marcas de canto cinza, instrução de impressão a 100%).
- **`tools/base.svg` gerado:** A4 paisagem, margem **10 mm**, marcador **16 mm**, `DICT_4X4_50` → **32 marcadores**,
  miolo branco **233×146 mm** (folga p/ o thermpro ~117×107).
- **Validação:** 10 testes novos (`test_calibration_target.py`) — layout (margem/moldura/miolo/IDs) + **detecção
  sintética** (renderiza→`detectMarkers` acha os 32; `findHomography` recupera lado = 16 mm; **sob perspectiva
  conhecida**, lados uniformes em todo o campo). Além disso, **prova no arquivo real:** rasterizei `base.svg` (Inkscape
  200 dpi) → **32/32 detectados**, lado recuperado **15,90 mm** vs 16 (0,1 mm = arredondamento do raster, std 0,05).
  Suíte **47→57**.
- **Guia de enquadramento "nadir" (adicionado):** a pedido do usuário, `render_svg` desenha no miolo um **anel
  concêntrico + cruz de centragem + ticks cardeais** em cinza-claro (`#cccccc`, traço 0,3 mm). Motivo: um círculo só
  aparece **redondo** se a câmera estiver a 90° do papel; sob inclinação vira **elipse** (`cos θ = eixo_menor/maior`) —
  ajuda o olho a mirar reto na hora da foto. Raio = menor metade do miolo − 5 mm (círculo **verdadeiro**, não elipse),
  perímetro fora da pegada do objeto → sobram arcos visíveis ao redor. Cinza bem acima do limiar de binarização, então
  **não polui** a segmentação do objeto escuro. **Prova:** re-rasterizado, ainda **32/32**, lado **15,90 mm**, std 0,05
  (idêntico — o guia é transparente p/ o detector). A medição **rigorosa** de inclinação fica para a Etapa B
  (decompor a pose dos ArUco e avisar se passar de ~3–5°); o anel é só o auxílio visual ao vivo.

### Etapa B — refactor para a base ArUco (foto real validada) ✅ (2026-06-24)
O usuário imprimiu a `base.svg`, fotografou o ThermoPro no centro (`tools/thermpro.jpg`) e pediu **refatorar tudo
para sempre usar essa base** (+ documentar a exigência no manual e no workflow). Diagnóstico na foto real: **32/32
marcadores**, lado reprojetado **15,87 mm** (alvo 16, σ 0,12), inclinação **~1°** → a base é mensurável e quase
nadir. Decisão: a moldura ArUco vira a **única** base; o subsistema de grade sai inteiro.

- **`rectify` reescrito (homografia ArUco):** `detect_markers` (`cv2.aruco.detectMarkers`) → `aruco_correspondences`
  casa ID↔cantos nominais (contrato de `calibration_target.homography_correspondences`) → `findHomography(RANSAC)`
  imagem→mm. **Retifica recortando o miolo branco** para um canvas métrico de escala **uniforme** `PX_PER_MM` px/mm
  (marcadores e anel-guia ficam fora do recorte). `estimate_tilt_deg` decompõe a pose (intrínseca aproximada) e
  **avisa** se a foto passou de `TILT_WARN_DEG` do nadir (paralaxe pela altura). `< MIN_MARKERS` → `GridDetectionError`.
- **Segmentação reescrita (objeto sobre branco):** `segment_tool` amostra a **moldura da borda** do canvas (fundo
  branco garantido, objeto central) p/ modelar o branco (auto-adapta à luz); pixel é objeto se **colorido**
  (saturação ≥ fundo + `SEG_SAT_MARGIN`) **OU escuro** (V ≤ `SEG_VAL_FRAC`×fundo) — a **sombra** suave (dessaturada,
  pouco mais escura) fica no fundo. Aposentou a máscara `NOT(verde)` (`GREEN_HSV_*`). Validei a regra em probes nos
  pixels reais (a regra (sat|escuro) rejeitou a sombra melhor que limiar de branco ou distância Lab).
- **Apagado (~270 linhas):** todo o detector de grade — `_detect_grid_lines`/`_grid_lines_mask`/`_hough_on_mask`/
  `_hough_segments`/`_cluster_grid_lines`/`homography_from_grid`/`_lattice_filter`/`_lattice_spacing`/`_axis_period`/
  `_edge_profile_peaks`/`_detect_grid`/`_grid_homography`/`_warp_to_canvas`/`line_*`/`fit_line_tls`/
  `assign_lattice_indices`/`classify_lines`/`grid_spacing`/`measure_grid_squares` — e os args `--grid-mm`/`--line-mm`.
  Mantida toda a metade de geometria (filete, low-pass, Béziers ancoradas, snap de bbox, SVG) — intacta.
- **Resultado (`thermpro.jpg`):** objeto **67,75 × 74,38 mm**, **23 Béziers** ancoradas, encaixe **0,9967**, linha
  limpa; `thermpro.svg` gerado. Contorno conferido (overlay): quadrado arredondado fiel; borda inferior (sombra)
  denoisada pelo low-pass.
- **Testes:** removi os de grade; adicionei `TestRectifyAruco` (cena ArUco sintética: canvas métrico uniforme,
  tamanho do objeto recuperado **inclusive sob keystone**, aborta sem marcadores, inclinação ~0 frontal / cresce sob
  warp) e repontei a ponta-a-ponta p/ `thermpro.jpg` (`TestEndToEndThermpro`: 32/32, escala plausível, encaixe ≥
  0,99, linha limpa, poucos nós, SVG = dimensão medida). **Suíte 48/48 verde** (com `test_calibration_target`).
- **Docs:** spec 12 (pipeline/API/CLI/constantes/testes/decisões), `Manual.html` ("Do JPG ao contorno" + workflow:
  imprimir `base.svg`, foto nadir, novo CLI sem `--grid-mm`), este progresso e o índice.

## Refino 8 — tratamento de luz (flat-field) + sombra de contato + matiz (2026-06-24, a pedido do usuário)

Usuário: "o grande problema é a **sombra do objeto** dificultando o traçado; inclua uma etapa de **tratamento de
luz / remover sombras antes do contorno**". Foco do ciclo: só essa parte inicial; teste **visual** (output salvo,
usuário aprova). Diagnóstico em probes/recortes da `thermpro.jpg` mostrou que havia **duas** sombras distintas, com
causas e soluções diferentes — não uma só:

- **Sombra difusa (halo)** ao redor da peça: V≈205, **acima** do corte de escuro (0,5·fundo=117) → **não** era a
  causa do contorno ruim, mas dimmava o branco perto da peça (limiar global caía no gradiente).
- **Sombra de CONTATO** (faixa fofa e escura colada na base, V≈90–130): **era** a causa do **serrilhado da base** —
  o teste de escuro (`V≤0,5·fundo`) a abocanhava e o cruzamento ruidoso do limiar serrilhava a borda inferior.

Três consertos, avaliados visualmente em etapas:

1. **Estágio 1b `normalize_illumination` (flat-field)** — entre `rectify` e `segment_tool`. A sombra difusa é
   escurecimento **suave e multiplicativo** do branco; estima o campo de luz `L(x,y)` por **closing em escala-cinza**
   (kernel > objeto, "pinta" a peça com o branco ao redor) + borrão gaussiano, em escala reduzida (`ILLUM_SCALE`)
   p/ velocidade, e **divide** a imagem por `L` (ganho **hue-preserving** nos 3 canais, teto `ILLUM_MAX_GAIN`).
   Salva `01b_flat.png`/`01b_illumination.png`. Resultado: fundo branco uniforme, halo atenuado. **Não** remove a
   sombra de contato (local, dentro da estimativa de `L`) — registrado no docstring. Usuário aprovou o flat isolado.
2. **Limiar de escuro `SEG_VAL_FRAC` 0,5 → 0,30** — exclui a sombra de contato (V≈90–130) mantendo o corpo preto
   real (V≈30–50). **Este matou o serrilhado.** A altura medida caiu **74,38 → 68,12 mm** (os ~6 mm a mais eram a
   franja-fantasma da sombra de contato somada à base).
3. **Termo de matiz `chromatic` em `segment_tool`** — a borda laranja **arredondada com realce** baixa a saturação
   abaixo do corte de `colored` (S≥fundo+45) e virava uma **mossa** no canto direito. Como o fundo é azulado
   (matiz OpenCV ~107) e o laranja é quente (~0–10), aceito o pixel pela **distância circular de matiz** ao fundo
   (`SEG_HUE_MARGIN`) gated por `S ≥ SEG_HUE_SAT_MIN` (acima do ruído do fundo) — recupera a borda sem pegar o branco.

**Resultado (`thermpro.jpg`):** base **lisa e arredondada** (era serrilhada), topo suave (o "biquinho" some na
suavização por Bézier ancorada), mossa direita preenchida — sobra só uma **ondulação pequena no canto sup. direito**
(em parte borda real laranja↔bezel + resíduo de realce). **22 Béziers**, encaixe 0,9971, objeto **67,62 × 68,62 mm**.
Parado aqui de propósito p/ **não viciar** o algoritmo nesta única foto; pendente validar com mais fotos. A cor do
objeto **não** precisa ser preservada em etapa alguma (decisão do usuário) — só interessa o contorno mais externo.

- **Cor é descartável:** decisão do usuário libera futuras etapas a ignorar fidelidade de cor (só silhueta importa).
- **Constantes novas:** `ILLUM_SCALE=0.125`, `ILLUM_KERNEL_FRAC=0.9`, `ILLUM_MAX_GAIN=3.0`, `SEG_HUE_MARGIN=25`,
  `SEG_HUE_SAT_MIN=60`; `SEG_VAL_FRAC` 0,5→0,30.
- **Sem testes automatizados neste ciclo** (a pedido do usuário — validação visual). `tools/_shadow_out/` (saída de
  debug visual) adicionado ao `.gitignore`.
- **Tocados:** `tools/photo_to_outline.py` (estágio 1b + segment_tool com matiz + limiar), `.gitignore`.

## Refino 9 — simetria do objeto (espelho + média das metades) (2026-06-24, a pedido do usuário)

Usuário: "muitos objetos são **homogêneos** — se você traça uma linha no meio (vertical), os contornos dos dois
lados são iguais. Crie um argumento para eu **informar o sentido da simetria** (horizontal/vertical); com isso você
tem **2 amostras** para aprimorar o contorno." Liberou TDD neste ciclo (foco só no script do SVG).

- **Insight:** num objeto simétrico, a metade esquerda e a direita (ou topo/baixo) são **duas medições do MESMO
  contorno**. Espelhar e fazer a **média** cancela o ruído **assimétrico** da foto (sombra/realce de um lado só,
  serrilhado de uma borda) e **força a simetria perfeita** — exatamente o "aprimorar com 2 amostras" pedido.
- **Onde:** novo **estágio 2b** entre `segment_tool` e `extract_outline` (atua na **máscara**, antes de virar mm/
  Béziers) → todo o resto do pipeline (contorno, snap de bbox, ajuste ancorado) herda a máscara limpa.
- **Como (`symmetrize_mask`):** acha o eixo a partir do **centroide** (`cv2.moments`) e **refina por máx. IoU**
  entre a máscara e seu espelho varrendo ±`SYM_SEARCH_MM` a 0,5 px (robusto a ruído/leve perspectiva). A "média de
  duas formas" é feita pelo **campo de distância COM SINAL** (`_signed_distance`: dist. p/ dentro − dist. p/ fora;
  >0 dentro, <0 fora): médio os dois campos e corto em 0 → a **média morfológica**. Escolhi SDF e **não** AND
  (interseção, enviesa p/ dentro = peça não cabe) nem OR (união, enviesa p/ fora = cavidade folgada demais). Eixo
  reflexão via `warpAffine` (matriz de reflexão em x=c ou y=c). `--symmetry` ∈ `{none,vertical,horizontal,both}`;
  `both` aplica os dois eixos em sequência (recursão).
- **Resultado (`thermpro.jpg`, simetria vertical):** auto-simetria da máscara **0,972 → 1,000**; contorno final
  **22 → 19 Béziers**, encaixe **0,9971 → 0,9975**, mesma dimensão (67,62 × 68,62 mm). A **"ondulação no canto sup.
  direito"** (pendência registrada no Refino 8) **some**: vira a média simétrica do canto esquerdo (overlay
  vermelho cru × verde simetrizado conferido visualmente). `both` deu 24 Béziers (impõe também topo/baixo, que o
  ThermoPro **não** tem perfeitamente → menos indicado aqui; serve a peças com dupla simetria).
- **Constante:** `SYM_SEARCH_MM = 4.0`. **CLI:** `--symmetry` (default `none`); reportado na saída quando ativo.
- **Sem testes automatizados** (TDD liberado pelo usuário); validação por overlay + métrica de auto-IoU/encaixe.
- **Tocados:** `tools/photo_to_outline.py` (estágio 2b: `symmetrize_mask`/`_signed_distance`/`_reflect_mask`,
  arg `--symmetry`, threading em `generate_outline`/`main`), `specs/12-foto-para-contorno.md`, este progresso, índice.

## Refino 10 — sombra/topo preto: histerese de escuro (`--shadow`) (2026-06-24, a pedido do usuário)

Usuário: "estamos tendo **problemas com a remoção das sombras**. Faça um argumento para removê-la e testar de novo.
A **altura do objeto parece menor do que precisa** — acho que ele não reconhece corretamente o **topo preto**."

- **Diagnóstico (com `--debug-dir`, lendo os PNGs):** o flat-field já apaga a sombra suave (acima do topo o papel
  volta a V≈232). O problema **não** era sombra *incluída*: era a **borda do topo preto sendo comida**. Medições no
  topo: núcleo preto V mediana **59** (escuro de verdade), mas a borda sobe numa **rampa** preto→sombra→papel. O
  corte único `dark = V ≤ 0,30·fundo (=70)` cortava **dentro dessa rampa** → ora pegava, ora perdia pixel → **borda
  serrilhada e topo encolhido** (zoom no topo confirmou). Daí a altura menor que o real.
- **Correção — histerese estilo Canny (`--shadow remove`):** mantém o **núcleo preto certo** (≤ `SEG_VAL_FRAC`·fundo)
  e o **cresce** pelos pixels escuros vizinhos (≤ `SEG_VAL_WEAK_FRAC`·fundo) até bater no papel claro, recuperando a
  borda real. **1ª tentativa (flood irrestrito) vazou feio:** altura 68,6 → **81,4 mm**, um blob inundando o anel de
  sombra de contato — porque a peça inteira (laranja inclusive) é um só componente fraco que toca o núcleo preto.
  **Conserto:** crescimento por **dilatação geodésica de alcance LIMITADO** (`SEG_SHADOW_GROW_MM = 2,0`, condicionada
  ao mask fraco) — cobre só a rampa da borda, não inunda o anel. A fina sombra que entra **engorda** o contorno (a
  peça cabe), no sentido oposto ao "topo comido".
- **Resultado (`thermpro.jpg`):** altura **68,62 → 71,50 mm** (~3 mm que faltavam), largura praticamente igual; topo
  preto agora hugga a borda real (overlay/zoom conferidos). Com `--shadow remove --symmetry vertical` (fluxo final):
  **67,88 × 71,38 mm**, **28 Béziers**, encaixe **0,9974**. `thermpro.svg` regenerado com essa combinação.
- **Constantes:** `SEG_VAL_WEAK_FRAC = 0.65`, `SEG_SHADOW_GROW_MM = 2.0`. **CLI:** `--shadow {off,remove}` (default
  `off`, preserva o comportamento antigo); reportado na saída quando ativo. Também corrigi o doc da spec, que listava
  `SEG_VAL_FRAC = 0.5` (o código usa **0.30**).
- **Testes:** suíte OpenSCAD **32/32** e suíte de imagem **38/38** verdes (parâmetros novos têm default → assinaturas
  retrocompatíveis). Validação do ganho por overlay/zoom + métrica de dimensão (TDD liberado pelo usuário).
- **Overlay automático (a pedido do usuário, no mesmo ciclo):** "produza SEMPRE um overlay, antes de sair o `.svg`,
  com prefixo `_overlay`." Novo `write_overlay(rect, mask, path)` e `overlay_path` em `generate_outline`; o `main`
  grava `_overlay_<nome>.png` ao lado do `.svg` a cada execução (underscore inicial = rascunho; `tools/_overlay_*` no
  `.gitignore`). Mostra o contorno segmentado (já com a simetria) em vermelho sobre a foto retificada — exato (px),
  p/ conferir segmentação/iluminação de relance. Usuário vai **trocar a foto** por uma com iluminação melhor (o ganho
  do Refino 10 ajudou mas não resolveu de todo); o overlay agora deixa essa validação imediata.
- **Overlay SVG editável (a pedido do usuário, no mesmo ciclo):** "consegue uma saída intermediária p/ eu acabar de
  ajustar no Inkscape? O overlay com `.svg`." Novo `write_overlay_svg(rect, cubics, mmpp_x, mmpp_y, path)`: monta um
  SVG com a **foto retificada embutida** (`<image>` base64, camada Inkscape `foto` TRAVADA via
  `sodipodi:insensitive`) + os **MESMOS Béziers do `.svg`** (camada `contorno`, vermelho, editável), tudo no
  **referencial métrico do canvas** (`viewBox` em mm, 233×146). Frame da foto = `(x_mm, −y_mm)` (px topo-esq), então
  o contorno cai **exato** sobre o objeto — validado: bbox do path x 83,3..151,1 mm ≡ região do objeto, tamanho
  67,88×71,9 mm. Fluxo: ajustar os nós sobre a foto, apagar a camada `foto`, exportar → contorno corrigido na escala
  real. `generate_outline` ganhou `overlay_svg_path` e `simplify_mm` (p/ casar o ajuste ancorado do `.svg`); `main`
  grava `_overlay_<nome>.svg` ao lado do PNG. Embute o PNG cru (~1,9 MB base64) — arquivo de rascunho local.
- **Overlay editável vira opt-in + saída com preenchimento (a pedido do usuário, no mesmo ciclo):** (1) o overlay
  SVG editável passou a ser **opt-in** via **`--inkscape`** (o PNG continua saindo sempre); (2) o **vetor de saída**
  deixou de ser só contorno — agora tem **contorno + preenchimento translúcido** numa cor bem destacada
  (`OUTLINE_COLOR = "#ff00ff"` magenta) a **`OUTLINE_FILL_OPACITY = 0.25`** (quase transparente), p/ **sobrepor todo o
  objeto** e conferir de relance se o contorno o cobre (qualquer parte de fora = contorno curto). Mesmo estilo no
  `.svg` final e na camada `contorno` do overlay editável. `svg_to_scad.py` usa só a geometria do `d` (ignora estilo),
  então não quebra. Prévia fiel (fill 25 % sobre a foto) conferida visualmente: cobre o ThermoPro inteiro.
- **Tocados:** `tools/photo_to_outline.py` (histerese em `segment_tool`, arg `--shadow`; `write_overlay`/
  `write_overlay_svg` + `overlay_path`/`overlay_svg_path`/`simplify_mm`, flag `--inkscape`, constantes
  `OUTLINE_COLOR`/`OUTLINE_FILL_OPACITY` + novo estilo preenchido em `polygon_to_svg`/`write_overlay_svg`, threading em
  `generate_outline`/`main`; `import base64`), `tools/thermpro.svg` (regenerado, agora preenchido), `.gitignore`,
  `specs/12-foto-para-contorno.md`, este progresso, índice. Suítes 32/32 e 38/38 verdes.

## Refino 11 — nós todos suaves + limite de cantos (`--max-nodes`) (2026-06-25, a pedido do usuário)

Aprendizado a partir do `_overlay` **editado à mão pelo usuário no Inkscape** (ele mandou comparar com a saída
anterior). Comparação numérica (parser de path próprio, amostragem das Béziers, alinhamento por bbox): **tamanho
estava certo** — bbox 67,88×71,38 (auto) vs 68,02×71,02 (edit), Δ ≤ 0,5 %; área Δ 0,3 %; desvio médio entre os dois
contornos **0,515 mm** (máx 1,86). O que o usuário mudou foi o **detalhamento**: **28 → 18 nós**, marcando 8 como
*smooth* (tangente contínua) e 10 *cusp*. Diagnóstico: o ajuste auto **super-segmentava** e emitia **só cusps** (cada
Bézier independente), facetando os cantos arredondados; o erro se concentrava numa extremidade (~0,9 mm), enquanto as
laterais retas já casavam (~0,25 mm). O usuário pediu: **todos os cantos suaves** e a **quantidade de cantos como
parâmetro** (p/ forçar menos).

- **Todo nó suave (G1).** `fit_closed_beziers_anchored` agora compartilha a tangente em cada âncora entre os dois
  trechos vizinhos (`_anchor_tangents` = corda pelos vizinhos imediatos no `rp`): a curva que chega e a que sai ficam
  colineares → sem bico. Antes, `t1`/`t2` vinham da direção local de cada trecho, independentes → cusp em toda âncora.
  Os splits internos de contenção (`_fit_cubic_recursive`) já eram suaves (tangente `tc` espelhada); agora as âncoras
  também são. A contenção (`_fit_segment_contained`, penetração ≤ `eps`) é preservada — onde a tangente suave estufaria
  p/ dentro, o trecho subdivide, mas continua suave nas pontas.
- **`--max-nodes N` (novo, `MAX_NODES = 0`).** Limite RÍGIDO de cantos: `_limit_anchors` remove iterativamente a âncora
  **menos significativa** (a mais quase-colinear com as vizinhas — menor desvio se omitida) até sobrarem ≤ N. 0 =
  automático (todas as extremidades do fecho). Threading: `fit_closed_beziers_anchored` → `polygon_to_svg` →
  `generate_outline` → `main` (+ arg CLI). O resumo do `main` mostra "nós suaves" e o limite, se houver.
- **Resultado (run do zero, só a foto):** `--shadow remove --symmetry vertical --inkscape` →
  **18 Béziers, encaixe 0,9982** (era 28 nós / 0,9974 — **menos nós E mais contido**), 67,88×71,38 mm. Bate com o
  ideal editado à mão pelo usuário (18 nós), sem precisar do `--max-nodes`. Conferido visualmente: fill magenta 25 %
  cobre o ThermoPro inteiro, cantos arredondados lisos.
- **TDD:** novos `test_anchored_all_nodes_smooth` (cross das tangentes em cada junção < 1e-3, dot > 0 — todos G1) e
  `test_max_nodes_caps_corners` (círculo com `max_nodes=6` → ≤ 6 nós, ainda contém ≥ 0,97). Suíte de imagem **50/50**
  verde (era 38; +12 inclui os 2 novos e a renumeração das classes), incl. ponta-a-ponta thermpro `coverage ≥ 0,99`.
- **Tocados:** `tools/photo_to_outline.py` (`_anchor_tangents`, `_limit_anchors`, reescrita do anchored com tangentes
  compartilhadas; `MAX_NODES`; arg `--max-nodes`; threading em `polygon_to_svg`/`generate_outline`/`main`),
  `tools/tests/test_photo_to_outline.py` (2 testes novos), `tools/thermpro.svg` (regenerado, 18 nós suaves),
  `specs/12-foto-para-contorno.md`, este progresso, índice.

## Pendências / futuro

- **Objeto claro/dessaturado** (ex. peça metálica fosca): a segmentação (colorido OU escuro) pode confundi-lo com o
  miolo branco. Premissa da Opção B (centro branco) — uma variante de **base escura** resolveria; documentar se surgir.
- Paralaxe pela **altura** do objeto continua sem correção (nenhuma base resolve); hoje o tool **mede e avisa** a
  inclinação. Futuro: correção por altura conhecida.
- Se o contorno tocar a borda da imagem (peça grande/descentrada), avisar; o miolo de 233×146 mm cobre folgado o
  thermpro.
- **Ondulação residual no canto sup. direito** do thermpro (realce na borda laranja↔bezel) — não atacada p/ evitar
  overfit a uma foto. Revisitar com **mais fotos-exemplo** (formas/cores variadas) antes de calibrar mais fino.
- **Sem testes automatizados** no Refino 8 (validação visual a pedido do usuário); ao estabilizar, formalizar um
  teste do tratamento de luz (ex.: `boundary_roughness` da base abaixo de um limite com/sem o estágio 1b).
- Usuário tem **mais ideias a implementar** neste fluxo (próximos ciclos).
