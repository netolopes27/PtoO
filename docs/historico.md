# Histórico — PtoO

Evolução condensada do PtoO (foto sobre a base de calibração → SVG do contorno em mm para
**gridfinity personalizável**). Arquitetura/API: [design.md](design.md); uso:
[README.md](../README.md). Datas em 2026.

> O PtoO foi **extraído** de um projeto OpenSCAD (Gridfinity), onde o SVG alimentava um item
> holder. As etapas iniciais citam objetos/bases já trocados (a serra → o ThermoPro; a grade de
> quadrados → a moldura ArUco). Estado atual: ver [design.md](design.md).

## Origem — calibração por grade

Tool nova `photo_to_outline.py`: de uma **foto** de um objeto sobre base quadriculada → **SVG em
mm** com o contorno externo, corrigido de escala/ângulo pela grade e suavizado p/ impressão (a
pedido do usuário: caixas custom a partir de foto, não de traçado manual).

- **Stack:** `numpy` + `opencv-python` em venv isolado (wheel abi3 cobre Python 3.14); resto
  stdlib.
- **Calibração pela grade** por autocorrelação do perfil de bordas (Sobel→projeção→autocorr,
  pico sub-pixel), não Hough — robusto à oclusão. Confiança baixa aborta (`GridDetectionError`)
  em vez de emitir escala errada.
- **Suavização p/ impressão:** `enforce_min_radius` (filete morfológico) → low-pass forte
  `lowpass_closed(--smooth-mm)` → decimação `approxPolyDP`. Métricas `coverage` e
  `boundary_roughness`.
- **Raio sem viés:** `min_corner_radius` usa circunraio com vizinhos afastados ~`window` mm (os
  imediatos subestimam ~28%).

## Refinos do traçado (Béziers)

- **Fundo removido / Béziers:** SVG passou a só contorno (sem `<rect>`) e em **cúbicas**
  (Schneider) em vez de polyline (`fit_closed_beziers`: cantos por ângulo com NMS circular +
  ajuste recursivo).
- **Mínimo de Béziers por contenção** (regra do usuário: só Béziers, na menor quantidade, com a
  peça **cabendo**): `fit_closed_beziers_contained` varre tolerâncias e fica com a **maior** cuja
  curva não penetra além de `eps` (`_floor_field`/`_max_penetration` via `distanceTransform`).
  Descoberta: recursão por contenção pura estufa p/ fora; o mínimo vem variando a **tolerância**,
  não trocando o algoritmo.
- **Reinício limpo do JPG:** removidas as referências desenhadas à mão (muleta que induzia viés);
  testes ponta-a-ponta refeitos medindo escala/encaixe contra a silhueta do JPG.

## Escala correta + fluxo travado

- **Escala pela grade corrigida:** autocorrelação trocada por regressão de treliça (robusta a
  linhas espúrias) e **anisotropia** tratada (X ≠ Y) — `rectify` passou a medir escala **por
  eixo**. `_scale_cubics_to_bbox` faz snap da bbox na dimensão medida.
- **Espessura no período da grade:** o espaçamento é o período linha-a-linha (quadrado + linha);
  corrigido com `período = grid_mm + line_mm` (antes subdimensionava ~9%).
- **Etapa 1 sem ganho:** `CLEARANCE_MM` foi a **0** — contorno no tamanho real, folga 100% a
  jusante (OpenSCAD/escala/edição manual), p/ não acumular ganho.
- **Traçado ancorado nas extremidades** (ideia do usuário): `fit_closed_beziers_anchored` denoisa,
  fixa âncoras nos vértices dominantes do fecho convexo e ajusta cúbicas contidas — ancorar nos
  pontos mais distantes garante caber. `--simplify` = nº de nós × justeza.

## Migração para a base ArUco

Usuário trocou peça (**serra → ThermoPro**) e base (grade → moldura ArUco). A grade era anônima
(orientação ambígua), casada por linha grossa e com **linha preta confundível com a borda preta
do objeto**. A moldura ArUco resolve isso e o objeto fica no miolo branco → segmentação trivial
**por design físico**.

- **Novo alvo** (`calibration_target.py` puro + `make_calibration_target.py`): marcadores com IDs
  sequenciais, miolo branco, contrato `homography_correspondences()`. `base.svg`: A4 paisagem,
  margem 10 mm, marcador 16 mm, `DICT_4X4_50` → 32 marcadores, miolo 233×146 mm. **Anel-guia
  "nadir"** cinza no miolo. Validado: 32/32 detectados, lado ~15,9 vs 16 mm.
- **`rectify` reescrito (homografia ArUco):** `detect_markers` → `aruco_correspondences` →
  `findHomography(RANSAC)` imagem→mm; recorta o miolo num canvas uniforme `PX_PER_MM`;
  `estimate_tilt_deg` avisa acima de `TILT_WARN_DEG`.
- **Segmentação reescrita (objeto sobre branco):** `segment_tool` amostra a moldura da borda p/
  modelar o branco (auto-adapta à luz); objeto = colorido OU escuro. Apagado o detector de grade
  (~270 linhas) e os args `--grid-mm`/`--line-mm`. Validado em `thermpro.jpg`: 32/32, lado 15,87
  mm, inclinação ~1°.

## Luz, sombra e simetria

- **Flat-field (`normalize_illumination`):** estima o campo de luz por closing em escala-cinza +
  borrão e **divide** a imagem (hue-preserving, teto `ILLUM_MAX_GAIN`).
- **Limiar de escuro `SEG_VAL_FRAC` → 0,30:** exclui a sombra de contato (V≈90–130) mantendo o
  corpo preto (V≈30–50). Matou o serrilhado da base.
- **Termo de matiz (`chromatic`):** aceita a borda laranja que perde saturação no realce, pela
  distância circular de matiz ao fundo (`SEG_HUE_MARGIN`/`SEG_HUE_SAT_MIN`).
- **Simetria (`--symmetry`):** as duas metades são duas medições do mesmo contorno;
  `symmetrize_mask` acha o eixo pelo centroide, refina por máx. IoU e faz a média pelo campo de
  distância com sinal (`_signed_distance`). `vertical`/`horizontal`/`both`.
- **Histerese de borda (`--shadow remove`):** diagnóstico — o problema não era sombra incluída, era
  a **borda do topo preto sendo comida** (corte único dentro da rampa preto→sombra→papel). Solução
  estilo Canny: mantém o núcleo certo e o **cresce** por dilatação geodésica de alcance limitado
  (`SEG_SHADOW_GROW_MM`). Estendida aos dois lados (bisel preto no topo **e** toe laranja no fundo),
  semeada pelos núcleos preto **e** colorido, com **piso de saturação** (`SEG_WEAK_SAT_MIN`)
  separando o plástico cromático da sombra de contato cinza.
- **Overlays automáticos:** a cada execução sai `_overlay_<nome>.png` antes do `.svg`;
  `--inkscape` gera também `_overlay_<nome>.svg` editável. O `.svg` passou a ter contorno +
  preenchimento translúcido magenta (`OUTLINE_COLOR`/`OUTLINE_FILL_OPACITY`).

## Pocket de encaixe por quadrante (estado atual)

Aprendizado do overlay editado à mão no Inkscape: o ajuste auto super-segmentava e só emitia
cusps, facetando os cantos arredondados. Pedido: **cantos suaves** e **quantidade de cantos como
parâmetro**.

- **Todo nó suave (G1):** `_anchor_tangents` compartilha a tangente em cada âncora entre os
  trechos vizinhos.
- **Modo POCKET por quadrante (default):** o padrão virou a **cavidade de encaixe** — divide a
  peça em 4 quadrantes, ancora as extremidades das pontas p/ dentro (`_quadrant_anchors`,
  espaçadas a ≥ `--min-dist` mm) e traça 1 cúbica suave por trecho que **contém** a peça
  (`_one_cubic_contained`, estufa só além de `POCKET_EPS_MM`). Prioridade dupla: **cabe** e fica
  **justa**. A densidade é ditada **só por `--min-dist`** (menor = mais âncoras = mais justo); o
  modo fiel/ilimitado (fecho convexo + snap de bbox) vem por **`--faithful`**.
  - *Evolução:* o `--max-nodes` (teto de curvas em passos de 4, com cota por quadrante) foi
    **removido** — era redundante com `--min-dist` (uma distância mínima já limita a contagem) e
    obrigava a casar dois controles. Agora a contagem emerge do espaçamento; `--faithful`
    substitui o antigo `--max-nodes 0`.
- **Saliências locais (`_protrusion_anchors`):** pico convexo no meio de uma aresta (pega/botão)
  ganha âncora se a proeminência ≥ `PROTRUSION_DEV_MM` (senão a curva arredondaria por cima).

## Estado de referência

- **Suíte 68/68 verde.**
- **`thermpro.jpg`** no default (POCKET, `--min-dist 10`): pocket contém a peça (coverage ≥ 0,99)
  ~ objeto. Apertando: `--shadow remove --min-dist 0.6 --smooth-mm 2 --symmetry vertical` → **305
  Béziers, contém 0.9999**, folga −0,18 × −0,00 (flush). `--faithful` (fiel) → ~19 Béziers, bbox =
  objeto. Com `--shadow remove` a borda arredondada entra dos dois lados e a sombra de contato
  cinza fica de fora.

## Skill `/ptoo` — calibrador iterativo (camada de workflow)

Acertar os parâmetros para um **pocket justo** exigia tentativa-e-erro manual (rodar → olhar o
overlay → ajustar flag → repetir). Virou uma **skill do Claude Code** em
`.claude/skills/ptoo/` (não toca na CLI; só a dirige). Invocação: `/ptoo <foto.jpg> --pass N
[--debug]`. Doc própria no `SKILL.md`; aqui só o registro da evolução.

- **Laço automático:** por passe roda a CLI (`--inkscape --debug-dir`), parseia as métricas do
  stdout (objeto, pocket, clearance, contém) e **inspeciona o contorno emitido com zoom** sobre a
  foto retificada, lado a lado com o segmentado (`scripts/zoom.py`, helper cv2 que rasteriza os
  Béziers do overlay editável — não há rasterizador SVG no ambiente). Diagnostica por uma tabela
  de heurísticas (sintoma → Δparâmetro) e recalibra em até `--pass N` tentativas.
- **Memória pequena** (`memory.md`, < 100 linhas): um **`start` dinâmico** = a melhor aposta atual
  (não um valor fixo — é o consenso/média recomputado do cache: mediana dos numéricos, maioria dos
  categóricos) + cache "último-bom" por objeto (≤5, evicta o mais antigo) + heurísticas. Começa
  perto do alvo em runs futuros: objeto conhecido parte da sua linha de cache; objeto novo, do
  `start`. Quanto mais objetos no cache, melhor a aposta.
- **Modo `--debug`:** além de calibrar, gera diagnóstico crítico da CLI (prosa com `file:line` +
  patch proposto, **não** aplicado) e grava um plano da **próxima versão decimal** em
  `docs/melhorias/v<next>.md` (incrementa só o decimal; a parte inteira é decisão do usuário).
- **Calibrado no thermpro:** alvo = pocket justo (clearance perto de 0) com **contém ≥ 0.9999**
  (gate rígido, a pedido do usuário). Aprendizados fixados na memória/heurísticas: a alavanca de
  densidade/contém é **`--min-dist`** (rampa de cima p/ baixo; parar no MAIOR que cruza 0.9999 —
  menos nós é melhor); `--smooth-mm` é só o lever fino e `--pocket-eps` quase não mexe;
  contra-intuitivo, **min-dist grande** (poucos nós) deixa o pocket frouxo E com contém baixo
  (Béziers longos arqueiam p/ dentro); e avaliar **simetria no 1º passe** (`--symmetry vertical`).

## Pendências / roadmap

- **Objeto claro/dessaturado** (peça metálica fosca) pode confundir-se com o miolo branco — uma
  variante de **base escura** resolveria.
- **Paralaxe pela altura** segue sem correção (nenhuma base resolve); hoje só mede e avisa.
  Futuro: correção por altura conhecida.
- **Ondulação residual** em bordas de alto contraste (laranja↔bezel) — revisitar com **mais
  fotos-exemplo** antes de calibrar mais fino (evitar overfit).
- **Avisar** quando o contorno tocar a borda da imagem (peça grande/descentrada).
