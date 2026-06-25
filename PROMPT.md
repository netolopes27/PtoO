# PROMPT.md — PtoO (Photo to Outline)

> Mova este arquivo para a raiz do novo projeto **PtoO** e renomeie para `PROMPT.md`
> (é o meta-prompt do projeto). Ele descreve a tool **já existente** — o código é
> **copiado**, não reescrito (ver "Arquivos a copiar" no fim). Use este doc para
> entender, rodar, testar e **estender** a tool.

## O que é

**PtoO** converte uma **foto** de um objeto apoiado numa **base de calibração impressa**
(moldura de marcadores ArUco + miolo branco) num **SVG em milímetros** com o **contorno
externo** do objeto — corrigido de perspectiva/inclinação pelos marcadores, na **escala
real** (mm verdadeiros) e **suavizado para impressão 3D** (sem cantos de 90°, sem bicos).

É uma ferramenta **Python de visão computacional autocontida**. Foi extraída de um projeto
OpenSCAD (Gridfinity), onde a saída SVG alimentava um item holder; aqui o fluxo **termina no
SVG**. Quem quiser levar o contorno para OpenSCAD pode usar o exportador opcional
`svg_to_scad.py` (ver fim).

**Entrada:** `thermpro.jpg` (foto do objeto na base `base.svg`) →
**Saída:** `thermpro.svg` (contorno em mm) + um overlay de conferência `_overlay_thermpro.png`.

## Convenções (obrigatórias)

- **Idioma:** todo o *código* (identificadores: variáveis, funções, módulos, nomes de
  arquivo) em **inglês americano**; toda a *documentação* (comentários, este prompt, docs)
  em **português do Brasil**. Unidades sempre **métricas (mm)**.
- **TDD-first:** ao mexer no comportamento, escreva/ajuste o teste **antes**. "Concluído" =
  suíte verde. Os parâmetros novos nascem com *default* para manter as assinaturas
  retrocompatíveis (os testes chamam sem os args novos).
- **Sem pip global:** as deps de visão (`numpy` + `opencv-python`) vivem **só** num venv
  isolado `./.venv/`. O resto é stdlib.

## Setup

Requer **Python 3.14** (há wheel abi3 do `opencv-python` que cobre 3.14; ver
`requirements.txt`).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt      # Linux/Mac
```

Sempre rode a tool e os testes **com o Python do venv**.

## Como rodar

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --symmetry vertical --inkscape
```

Flags principais:

| Flag | Default | O que faz |
|------|---------|-----------|
| `--in/-i` | (obrig.) | foto de entrada |
| `--out/-o` | `<in>.svg` | SVG de saída (mm) |
| `--dict` | `DICT_4X4_50` | dicionário ArUco da base; **deve casar** com `base.svg` |
| `--smooth-mm` | `8` | janela do low-pass que tira o serrilhado |
| `--clearance` | `0` | folga externa; **0 = tamanho real** (aplique a folga a jusante) |
| `--shadow` | `off` | `remove` liga a **histerese de borda** (recupera bisel preto do topo + toe laranja do fundo, barra a sombra cinza) |
| `--symmetry` | `none` | `vertical`/`horizontal`/`both`: espelha + faz a **média das metades** |
| `--simplify` | `2.0` | densidade das âncoras (mm): maior = menos nós; menor = mais justo |
| `--max-nodes` | `4` | **teto de curvas do POCKET de encaixe** (Béziers suaves), em passos de 4. Divide a peça em **quadrantes** e ancora a **extremidade** de cada setor (4 = 1/quadrante; +4 = mais 1/quadrante → mais justo); as curvas **contêm** a peça (toca/corta ≤ `POCKET_EPS_MM`). Não busca fidelidade máxima. `0` = modo ilimitado (contorno fiel, com snap de bbox) |
| `--min-dist` | `10` | distância **mínima (mm) entre âncoras do mesmo quadrante** no pocket: ao adensar (8, 12…), o 2º/3º ponto só entra se ficar a ≥ este valor dos já escolhidos ali (evita aglomerar nas pontas) |
| `--inkscape` | off | gera também o **overlay SVG editável** (foto embutida + Béziers em camadas) |
| `--polyline` | off | emite polilinha crua `L` em vez de curvas |
| `--debug-dir` | — | grava PNGs intermediários (retificada/máscara) p/ diagnóstico |

**A cada execução** sai sempre um overlay PNG de conferência `_overlay_<nome>.png` (contorno
segmentado em vermelho sobre a foto retificada) — confira segmentação/iluminação de relance
**antes** de aceitar o `.svg`. Com `--inkscape`, sai também `_overlay_<nome>.svg` (foto
retificada embutida em camada travada + o mesmo contorno em camada editável, no referencial
mm): abra no Inkscape, ajuste os nós sobre a foto, apague a camada da foto, exporte.

## A base de calibração impressa

Moldura de marcadores **ArUco** ao redor de uma folha **A4** com **miolo branco liso** onde
o objeto é apoiado. Escolhida (vs uma grade de quadrados) porque cada marcador tem **ID
único** (sem ambiguidade de orientação, robusto a oclusão), cantos **sub-pixel** (homografia
precisa via `cv2.aruco` nativo) e, sobretudo, **segmentação trivial**: o objeto fica sobre
branco, sem nenhuma linha para confundir com a borda preta da peça.

A tool **gera a própria base**, garantindo que *o impresso == o que o detector assume*:

```bash
.venv/Scripts/python make_calibration_target.py --out base.svg
```

Defaults: A4 paisagem, margem 10 mm, marcador 16 mm, `DICT_4X4_50` → **32 marcadores**,
miolo branco **233×146 mm**. **Imprima `base.svg` em A4 a 100%** (sem "ajustar à página"),
apoie a peça no centro branco e fotografe **de cima, o mais perto do nadir** (mire pelo
anel-guia cinza: só fica redondo na tela quando a câmera está perpendicular).

> ⚠️ Limite físico que **nenhuma** base corrige: o objeto tem altura → o topo flutua sobre o
> plano do papel (paralaxe), inflando/deslocando o contorno. Mitigado só fotografando perto
> do nadir. A tool **mede e avisa** a inclinação (`--debug`/saída).

## Pipeline (em `photo_to_outline.py`)

1. **Retificar por homografia.** `detect_markers` acha os ArUco e seus cantos sub-pixel;
   casa cada ID aos 4 cantos nominais em mm (`aruco_correspondences` ↔
   `calibration_target.homography_correspondences`); `findHomography(RANSAC)` resolve
   imagem→mm; `rectify` recorta o **miolo branco** num canvas métrico de escala **uniforme**
   `PX_PER_MM`. Estima e avisa a **inclinação** (`estimate_tilt_deg`). `< MIN_MARKERS` →
   `GridDetectionError`. **É daqui que sai a dimensão real do objeto.**
2. **Normalizar iluminação** (`normalize_illumination`, flat-field) e **segmentar**
   (`segment_tool`): o fundo é o miolo branco (amostrado na borda do canvas → auto-adapta ao
   balanço de branco). Pixel = objeto se **colorido** (saturação) **OU cromático** (matiz)
   **OU escuro** (brilho ≤ `SEG_VAL_FRAC`×fundo). Morfologia, maior componente conectado,
   preenche buracos. **`--shadow remove`** liga a **histerese de borda** (estilo Canny):
   cresce os núcleos **preto E colorido** pela borda arredondada que vira p/ a base — o
   **bisel PRETO no topo** e o **toe LARANJA dessaturado no fundo**, ambos caindo no vão entre
   `colored` e `dark` — só pelos pixels vizinhos **com croma** (`S ≥ SEG_WEAK_SAT_MIN`) por
   **dilatação geodésica de alcance limitado** (`SEG_SHADOW_GROW_MM`). Recupera a borda real
   dos dois lados que o corte único comia e **para na sombra de contato CINZA desaturada** da
   base (o piso de saturação separa o plástico cromático da sombra cinza → pocket justo).
   **`--symmetry`** espelha a máscara e faz a média das metades
   (duas amostras do mesmo contorno → menos ruído).
3. **Extrair contorno** (`extract_outline`): maior contorno → pontos em mm
   (x = px·mmpp ≥ 0, y = −px·mmpp ≤ 0, Y para cima).
4. **Suavizar para impressão** (`process_for_print`): low-pass `--smooth-mm`, raio mínimo de
   canto, `clearance`.
5. **Ajustar Béziers + emitir SVG** (`polygon_to_svg`). Modo padrão = **POCKET de encaixe
   por quadrante** (`fit_closed_beziers_anchored` com teto `--max-nodes > 0`): divide a
   peça em 4 quadrantes (em torno do meio da bbox), dá a cada um a cota `N//4` e ancora os
   pontos **mais externos** do quadrante, das pontas p/ dentro, com âncoras do **mesmo
   quadrante a ≥ `--min-dist` mm** (`_quadrant_anchors`) — a 1ª é a ponta, a 2ª/3ª caem
   ~`--min-dist` adiante (espalhadas, sem aglomerar). Além disso, **força uma âncora em cada
   saliência local** (`_protrusion_anchors`): um pico convexo no meio de uma aresta (pega/
   botão lateral) que o seletor radial ignoraria, com **proeminência ≥ `PROTRUSION_DEV_MM`**
   (0,8 mm) acima da vizinhança — entra **dentro do mesmo teto** (vagas de quadrante cedem,
   mantendo ≥ 4; só age com teto > 4). Entre âncoras, **1 cúbica suave por
   trecho** que **contém** a peça: parte do ajuste por mínimos quadrados e **estufa p/
   fora** (alonga os handles, preservando G1) só se penetrar além de `POCKET_EPS_MM`
   (`_one_cubic_contained`) — toleramos toque/corte sub-mm p/ não inflar por ruído. Emite
   **≤ teto** Béziers. **Não há snap de bbox** aqui — o pocket fica no tamanho métrico real,
   ~objeto (mais pontos = mais justo). `--max-nodes 0` = modo **ilimitado/fiel**: ancora no **fecho
   convexo** (RDP `--simplify`), subdivide cada trecho por contenção e **fixa a bbox (snap)
   na dimensão real** (`_scale_cubics_to_bbox`). **Todo nó é suave (G1)**: a tangente em
   cada âncora/corte é compartilhada entre os trechos vizinhos (`_anchor_tangents`) → sem
   bico, fácil de editar no Inkscape. Saída = **contorno + preenchimento translúcido**
   (magenta `OUTLINE_COLOR` a `OUTLINE_FILL_OPACITY=0.25`, que sobrepõe o objeto p/
   conferir cobertura).

## Constantes-chave (topo de `photo_to_outline.py`)

`PX_PER_MM = 8.0` · `DICT_NAME = "DICT_4X4_50"` · `MIN_MARKERS = 8` ·
`SEG_SAT_MARGIN = 45` · `SEG_VAL_FRAC = 0.30` (corte de escuro) ·
`SEG_VAL_WEAK_FRAC = 0.65` / `SEG_WEAK_SAT_MIN = 35` / `SEG_SHADOW_GROW_MM = 3.0` (histerese do `--shadow`) ·
`SEG_HUE_MARGIN = 25` / `SEG_HUE_SAT_MIN = 60` · `SYM_SEARCH_MM = 4.0` ·
`MIN_RADIUS_MM = 1.5` · `SMOOTH_MM = 8.0` · `CLEARANCE_MM = 0.0` ·
`ANCHOR_SIMPLIFY_MM = 2.0` · `MAX_NODES = 4` (teto de curvas do pocket; 0 = ilimitado) ·
`ANCHOR_EPS_MM = 0.08` (modo fiel) · `POCKET_EPS_MM = 0.5` (penetração tolerada no pocket) ·
`ANCHOR_MIN_DIST_MM = 10.0` (distância mín. entre âncoras do mesmo quadrante) ·
`PROTRUSION_DEV_MM = 0.8` (proeminência mín. de uma saliência local p/ virar âncora; teto > 4) ·
`CONTAIN_COVERAGE = 0.99` (abaixo disso, com teto, o CLI avisa) · `RASTER_PPM = 16.0` ·
`OUTLINE_COLOR = "#ff00ff"` / `OUTLINE_FILL_OPACITY = 0.25`.

## Testes

Suíte `unittest`, rodada **com o venv**:

```bash
.venv/Scripts/python tests/run_image_tests.py
```

Três níveis (ver `tests/test_photo_to_outline.py` e `tests/test_calibration_target.py`):

- **A. Unidade (puro):** geometria de polígono (área/CCW, RDP, Chaikin, raio mínimo,
  `coverage`, `boundary_roughness`), homografia, ajuste de Bézier. Inclui `TestAnchoredFit`:
  **todos os nós são suaves (G1)**; o **POCKET de encaixe** (`--max-nodes > 0`) ancora 1
  extremidade por quadrante/setor (`_quadrant_anchors`), respeita o **teto de curvas**
  (numa estrela côncava: livre usa muitas, teto 4 sai com ≤4) e **contém a peça** (coverage
  ~1, pocket ≥ objeto) em formas convexas e côncavas; default 4. `TestProtrusionAnchors`:
  uma **saliência no meio de uma aresta** ganha âncora própria (`_protrusion_anchors`), o
  pocket a alcança, curvatura suave (círculo) **não** gera âncora espúria, e o nó segue G1.
- **B. Sintético ArUco:** `numpy` gera uma cena com marcadores e um objeto de tamanho
  conhecido; `rectify` recupera o canvas métrico, a escala uniforme e o tamanho real
  inclusive sob keystone; aborta sem marcadores.
- **B2. Histerese de borda (`TestDeshadowHysteresis` + `TestRimToeHysteresis`):** dois
  canvas sintéticos espelhados. (1) bisel preto **cromático** (topo) + núcleo + sombra
  **cinza** → `--shadow remove` **recupera o bisel** (topo sobe ≥ 1 mm) e **rejeita a sombra**;
  o **piso de saturação** (`SEG_WEAK_SAT_MIN`) é o separador — zerá-lo faz a base inflar.
  (2) corpo colorido + **toe laranja dessaturado** (fundo) + sombra cinza → a mesma histerese,
  semeada pelo núcleo `colored`, **recupera o toe** (base desce ≥ 1 mm) e **para na sombra**.
- **C. Ponta-a-ponta:** contorno tirado **direto de `thermpro.jpg`** — escala pelos
  marcadores; no **modo ilimitado** (`max_nodes=0`) a peça **cabe** (`coverage ≥ 0.99`),
  linha limpa, **bbox do SVG = dimensão medida**; no **default (pocket teto 4)** o pocket
  **contém** a peça (`coverage ≥ 0.99`) ficando **≥ objeto** (sem snap).

Estado de referência: **60/60 verde**; `thermpro` no **default (POCKET teto 4)** sai
**73,29 × 74,62 mm** (objeto medido 67,88 × 71,38; folga +5,4 × +3,2), **4 Béziers (nós
suaves), contém a peça 0,9983** — `--max-nodes 8` aperta p/ folga ~+1,4 mm. A curva pode
**tocar/cortar de leve** a peça (até `POCKET_EPS_MM`) p/ não estufar por ruído sub-mm. Com
**`--max-nodes 0`** (ilimitado/fiel) sai **18 Béziers, bbox = objeto, encaixe 0,998**.
Com **`--shadow remove`** (histerese de borda + piso de saturação) a borda arredondada entra
dos dois lados: objeto **67,75 × 71,62 mm** (era 68,62 de altura sem ele — recupera ~2,6 mm de
preto no topo e ~0,4 mm de toe laranja no fundo) e a **sombra de contato cinza fica de fora**
nos dois (pocket justo, contém a peça 0,997).

## Estrutura do projeto (mantida igual à origem p/ não editar código)

```
PtoO/
  PROMPT.md                    ← este arquivo
  requirements.txt
  .gitignore
  photo_to_outline.py          ← a tool
  calibration_target.py        ← layout do alvo (puro, sem OpenCV)
  make_calibration_target.py   ← gera base.svg
  base.svg                     ← alvo de calibração (impressível)
  thermpro.jpg                 ← foto de exemplo (na raiz: os testes a procuram aqui)
  thermpro.svg                 ← saída de exemplo
  tests/
    test_photo_to_outline.py
    test_calibration_target.py
    run_image_tests.py
```

> **Importante:** os testes calculam os caminhos de forma relativa — `photo_to_outline.py` e
> `thermpro.jpg` precisam ficar na **raiz** do projeto e os testes em `tests/`. Mantendo este
> layout (espelho do `tools/` original), **nenhuma linha de código precisa mudar**.

## Roadmap / pendências herdadas

- **Objeto claro/dessaturado** (peça metálica fosca) pode se confundir com o miolo branco —
  uma variante de base escura resolveria.
- **Paralaxe pela altura** do objeto não é corrigida (nenhuma base resolve); hoje só mede e
  avisa a inclinação. Futuro: correção por altura conhecida.
- **Ondulação residual** em bordas de alto contraste (ex. laranja↔bezel) — revisitar com mais
  fotos-exemplo (formas/cores variadas) antes de calibrar mais fino, p/ não dar overfit.
- Avisar quando o contorno tocar a borda da imagem (peça grande/descentrada).
