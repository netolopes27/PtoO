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

## Sombra em corpo cinza-neutro + ressalto convexo (v0.5)

Validado em **4 fotos** da mesma trena (azul/contato, cinza/projetada, vista-de-cima/reflexo-rosa,
luz-difusa) que **nenhum cue único** (croma, valor, textura-de-borda) separa o corpo cinza-neutro da
sombra em todas as condições. O usuário traçou o contorno **ideal à mão** (`trena_esperado.svg`); a
comparação do-zero expôs que `--val-frac 0.68 --shadow off` **balona sobre a sombra projetada** (76 vs
65 mm) e o `contém 1.0000` **esconde** o erro (o gate não julga correção). Implementado:

- **`--shadow texture` (substitui a Etapa A do plano, rebaixada por overfit):** valor-primário pega o
  corpo escuro; a **textura** (std local de V, **limiar Otsu adaptativo** da própria foto) **recorta**
  as regiões lisas-E-mais-claras = a sombra projetada. O recorte é aplicado a **todo** o candidato
  (valor **e** croma) — necessário porque em fundo de papel **cromático** (lavanda saturada) a sombra
  também é cromática e voltaria pela porta do `colored|chromatic`. Trena cinza: 76→64,5 mm, sombra fora.
- **`--mask-smooth-keep-bumps` (Etapa B):** enviesa o `--mask-smooth-mm` p/ *closing* no campo de
  distância (`max(sdf, blur)`) — remove só reentrâncias côncavas (serrilha) e **preserva ressaltos
  convexos** (a aba lateral), que o borrado isotrópico arredondava junto.

Resíduos pendentes (rumo ao "contorno perfeito") em [Pendências / roadmap](#pendências--roadmap).

## Estado de referência

- **Suíte verde** (contagem canônica em [design.md](design.md) §Testes).
- **`thermpro.jpg`** no default (POCKET, `--min-dist 10`): pocket contém a peça (coverage ≥ 0,99)
  ~ objeto. Apertando: `--shadow remove --min-dist 0.6 --smooth-mm 2 --symmetry vertical` → **305
  Béziers, contém 0.9999**, folga −0,18 × −0,00 (flush). Somando `--mask-smooth-mm 2` (regulariza a
  silhueta) → **303 Béziers, contém 1.0000** com a borda PRETA lisa (some a ondulação). `--faithful`
  (fiel) → ~19 Béziers, bbox = objeto. Com `--shadow remove` a borda arredondada entra dos dois
  lados e a sombra de contato cinza fica de fora.

## Regularização da silhueta + refator (eficiência/tokens)

- **Ondulação da borda PRETA = problema de MÁSCARA, não de curva.** Onde o objeto preto quase se
  funde com a sombra, a segmentação serrilha; o `--smooth-mm` (low-pass da curva) é calibrado p/
  não comer features e deixa passar a ondulação de média amplitude. Decisão: limpar a forma **na
  fonte** com `regularize_silhouette` (borra o campo de distância com sinal e re-corta em 0 —
  reusa `_signed_distance` da simetria), atrás da flag `--mask-smooth-mm` (default 0). É um lever
  **ortogonal** ao `--smooth-mm`/gate: some com saliências/ondulações de raio < valor sem rebaixar
  o `contém` nem arredondar os cantos macro. No thermpro, `2` mm zerou a ondulação mantendo 1.0000.
- **Refator p/ tokens:** stdout do CLI compactado p/ 3 linhas parseáveis (chaves estáveis
  `obj`/`pocket`/`folga`/`contém`/`encaixe`); formatador de número SVG unificado em
  `calibration_target.fmt_mm` (fonte única dos 3 lugares); construção do `d` das cúbicas extraída
  p/ `_cubics_to_path_d`; o ajuste ancorado (passo mais caro) agora é **memoizado**
  (`fit_anchored_cached`) — antes recalculava até 3×/run.

## Skill `/ptoo` — calibrador iterativo (camada de workflow)

Acertar os parâmetros para um **pocket justo** exigia tentativa-e-erro manual (rodar → olhar o
overlay → ajustar flag → repetir). Virou uma **skill do Claude Code** em
`.claude/skills/ptoo/` (não toca na CLI; só a dirige). Invocação: `/ptoo <foto.jpg> --pass N
[--debug]`. Doc própria no `SKILL.md`; aqui só o registro da evolução.

- **Laço automático:** por passe roda a CLI (`--inkscape --debug-dir`), parseia as métricas do
  stdout (objeto, pocket, clearance, contém) e **inspeciona o contorno emitido com zoom** sobre a
  foto retificada, lado a lado com o segmentado (`.claude/skills/ptoo/scripts/zoom.py`, helper cv2 que rasteriza os
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

## Editor de nós embutido (`--edit`, v0.6)

Constatação do usuário: por melhor que a detecção fique, **sempre** sobra um ajuste manual fino
(sombra/realce na borda; ou traçar por dentro da peça de propósito, p/ aplicar offset global depois).
O caminho antigo era exportar `--inkscape` e mexer nos nós no Inkscape — fora da ferramenta. v0.6
traz esse ajuste **para dentro** da CLI.

- **Módulo novo `outline_editor.py`** (stdlib + cv2), em duas camadas: **núcleo puro** (testável) e
  **view tkinter** (glue fino). tkinter é stdlib (Tk 8.6 no Python do Windows); a foto entra via
  `cv2.imencode(PNG)` → base64 → `tk.PhotoImage` (sem PIL).
- **Flag `--edit`:** entre a detecção e a saída, abre uma janela com a **foto retificada** de fundo e
  os **nós da curva** como alças. Arrastar = mover; clique na curva = inserir; botão-direito = excluir;
  **rodinha = zoom no cursor** (o ponto sob o mouse fica parado, fundo por **recorte do viewport** →
  custo independente do zoom); **Ctrl + arrasto esquerdo = pan**. Botões (GUI em **inglês**): Re-trace,
  Undo, Reset, Finalize. **Re-trace** traça a curva suave G1 pelos nós (`cubics_through_nodes` — spline
  cardinal com tangente compartilhada de `_anchor_tangents`, `_cap_handles`/`_repair_self_intersections`);
  mover/inserir/excluir já re-traça.
- **WYSIWYG:** **Finalize** grava as mesmas saídas a partir de **EXATAMENTE a curva exibida**
  (`self.cubics`, o último Re-trace), emitida **literal** (sem snap de bbox). Uma 1ª tentativa fazia o
  Finalize re-ajustar a curva à silhueta detectada (botão "Suavizar", `cubics_through_anchored_silhouette`)
  e **atrapalhou**: ao mover um nó p/ *fora* da silhueta (ex.: incluir o pino do clipe) o algoritmo
  brigava com a intenção → bicos/dentes e queda de contenção. Lição do usuário: **o que se vê ao
  finalizar tem de ser o que é gravado** — a Suavizar e a função foram removidas.
- **Divisão de trabalho:** edita-se os **nós finais** (não a silhueta crua) — o usuário corrige a forma
  e a CLI re-traça a curva limpa. O `_overlay_<nome>.png` segue saindo (a skill `/ptoo` depende dele).
  Refator: o envelope SVG saiu p/ `_svg_from_cubics`/`_svg_envelope` (fonte única do `.svg` padrão e do
  editado). A skill `/ptoo` acrescenta `--edit` **só no último passe**, após a calibração convergir.

## Gate honesto + espigões finos (v0.7)

Caso real (`/ptoo trena.jpg`): o **gancho metálico da fita** (pino ~1×5 mm) era apagado pelo
`--mask-smooth-mm 2` e **nenhuma métrica acusava** — o `contém` era medido contra a silhueta
**pós**-regularização, validando uma silhueta já mutilada. Três mudanças:

- **P1 — `contém` honesto:** o CLI mede o `contém`/`encaixe` contra a silhueta de **REFERÊNCIA**
  pré `--mask-smooth-mm` (`generate_outline(..., return_silhouettes=True)` → `(out, sil, sil_ref)`),
  com **tolerância de profundidade** `CONTAIN_TOL_MM = 0.3` (erosão da referência no `coverage`):
  penetração rasa (serrilha de ruído) não conta; corte profundo (feature perdida) derruba o gate.
  Sem a tolerância o gate ficava inatingível (~0.9916 só de lascas de ruído no perímetro).
- **P2 — aviso de remoção:** `regularize_silhouette` compara a máscara antes/depois e **avisa**
  quando some uma saliência convexa com proeminência ≥ `PROTRUSION_DEV_MM` e área ≥ 1 mm²
  (`MASK_SMOOTH_WARN_AREA_MM2`), sugerindo `--mask-smooth-keep-bumps`.
- **P3 — `_preserve_spikes`:** o low-pass do `--smooth-mm` **recuava a ponta** de espigões finos
  antes da seleção de âncoras (o piso de contenção nascia sem ela). Agora os trechos crus
  proeminentes são reinjetados na curva suavizada — com dois filtros p/ não desfazer o
  trabalho do smooth: recuo ≥ `SPIKE_MIN_RECEDE_MM` (0.3; pico de serrilha recua ~0.1-0.2) e
  boca ≤ `SPIKE_MAX_WIDTH_MM` (3.0; canto/curvatura macro tem boca larga).

Resultado (trena): params antigos → WARNING + contém 0.9968 (acusa o gancho perdido);
`+ --mask-smooth-keep-bumps` → contém **1.0000** (gancho envolvido pelo pocket).
Suíte: 113 → **123** testes (`TestCoverageTolerance`, `TestPreserveSpikes`, avisos em
`TestRegularizeSilhouette`, `TestSilhouetteRef`).

## Refino de borda por watershed no `--shadow texture` (v0.8)

Caso real (`/ptoo trena.jpg`, trena CINZA em luz difusa): o subtrator por textura (v0.5) recorta a
sombra projetada "lisa E mais clara", mas a **UMBRA/sombra de contato** é lisa e **ESCURA** — passava
pelo recorte e inflava a silhueta ~4–5 mm na borda virada p/ ela (era a 1ª pendência do texture).
O cue que separa de verdade não é brilho, é **nitidez**: a borda física peça↔fundo é um **degrau**
de V; sombra↔papel é **rampa** suave. `_refine_edge_watershed` re-decide a fronteira pelo
gradiente (watershed com marcadores): FG = miolo erodido (`SEG_WS_ERODE_MM`) **menos** o
liso-e-meio-claro (`SEG_WS_FG_VAL_FRAC`, umbra provável); BG = fora da máscara dilatada
(`SEG_WS_BAND_MM`); a casca vira zona incerta — a inundação do papel atravessa a rampa e a da
peça esbarra no degrau. Medido na trena (perfil de V + zoom 3×): umbra 4–5 mm → resíduo
~0,5–1,5 mm, contorno colado na borda serrilhada sem comer corpo; obj 65.12×65.50 → 64.50×65.00.

## Fusão 2-fotos direcional + metal claro (v0.9)

Caso real (Raspberry Pi 2 ao sol duro): nenhum modo `--shadow` resolvia a sombra dura, e a
simetria não se aplica. Ideia (sessão `/ptoo`): **duas fotos, mudando só o lado da luz** —
girar **base+peça juntas** ~180° em relação ao sol e refotografar. As duas retificações ancoram
no mesmo alvo impresso → mesmo canvas métrico; em cada foto o lado **iluminado** tem borda limpa.
`--in2 <foto2>` (tudo automático; ver [design.md](design.md) §Pipeline 2b e [manual.md](manual.md)):

- **Registro rígido** (`_register_masks`): quartos {0,90,180,270}° + refino fino ±4° + translação
  ±10 mm, pontuados por **IoU × textura (ZNCC)**. Lições que viraram código: o IoU puro elegia
  rot=3° quando a peça foi girada ~180° (sombra∩sombra infla a rotação ERRADA em peça retangular);
  o refino fino precisa rodar em **todos** os quartos antes de eleger (o ZNCC só "encaixa" no
  ângulo exato); a semente de translação = diferença de centroides (a rotação gira em torno do
  centroide da máscara 2, deslocado pela sombra); e o registro roda nas máscaras **limpas** —
  com a sombra readmitida (faint-metal, abaixo) o IoU voltava a alinhar sombra com sombra
  (shift saltava 13 mm).
- **Fusão direcional por pixel disputado** (`fuse_masks`): direção da sombra de cada foto =
  centroide do **lóbulo exclusivo** relativo ao núcleo (AND); o núcleo sempre entra; pixel de
  lóbulo entra **só no lado iluminado da própria foto** — do lado da sombra dela, o excesso É
  sombra e cai. A 1ª versão (bissetriz/meio-plano) admitia sombra quando as direções não eram
  opostas; a regra por pixel degrada graciosamente p/ ~AND e **avisa** quando as sombras caem do
  mesmo lado (`FUSE_ALIGN_MAX`). A paralaxe deixou de roer conectores altos (não há AND na borda
  soberana) → `--fuse-grow` ficou opcional (resíduo perto da bissetriz, default 0).
- **Predicado faint-metal** (automático com `--in2`): na 2ª bateria de fotos (luz difusa), os
  topos METÁLICOS dos conectores sumiram da máscara — medido V = **1,005×fundo** no topo do USB
  (nenhum `--val-frac`/croma alcança; o pocket sairia com plástico onde os conectores entram, e o
  gate `contém` **não acusa** porque mede contra a própria máscara — só o zoom pegou). Saída: o
  metal tem **saturação fraca** (S ~18–31 vs ~8 do papel) → predicado S ≥ fundo+10 (V ≤
  1,05×fundo). Ele readmite a sombra (S~25) — proibitivo em foto única, **seguro aqui**: a fusão
  a remove. É o casamento dos dois mecanismos que torna ambos viáveis.
- **Overlay** usa de fundo a foto de **menor lóbulo** (melhor luz), warpada pelo registro.

Resultado (Pi 2, min-dist 1.2): obj **90.00×58.75 mm** = dimensões físicas reais (85 de placa +
pontas USB + microSD saltando), contém **1.0000**, folga −0.01/−0.10, 189 Béziers. Resíduo: nick
~1,5 mm num canto que ficou sombrio nas DUAS fotos (luzes não exatamente opostas) — corrigível
com `--edit` ou refotografando. Refactor: registro extraído p/ `_register_masks` (testável).
Suíte: 123 → **130** (`TestWatershedEdgeRefine`, `TestFaintMetal`, `TestFuseMasks`).

## Primitivas geométricas — retas e arcos (v0.10)

Observação do usuário: objetos reais têm **arestas retas** e o ajuste livre insiste em Béziers
que "tendem a reta" (no Pi, a rampa min-dist fechava alto e o canto do Ethernet custava +0.83 mm
de folga). Ideia: detectar **pontos quase-colineares logo após a extração**, suprimir os do meio
e ficar só com as extremidades — "compactação com formas geométricas conhecidas": primeiro
retas, depois arcos. Protótipos visuais sobre o Pi validaram a direção antes do código
(tol 0.3 mm: 17 retas + 15 arcos cobrindo 292/295 mm do perímetro).

- **Retas** (`_detect_line_runs`, `--line-tol`, default 0.3): trecho maximal com desvio à corda
  < tol; fusão de colineares (uma aresta = UMA reta); **veto por círculo** (círculo grande não
  vira polígono; no veto o cursor NÃO pula o trecho — a reta real pode começar adiante); pontas
  recuadas `PRIM_TRIM_MM`. Emissão: cúbica degenerada NA corda, **deslocada p/ fora** pelo
  desvio residual (reta-suporte: estufar cúbica colinear não a move de lado → o guard de
  contenção seria impotente; lição do teste `spread`).
- **Arcos** (`_detect_arc_runs`, `--arc-tol`): círculo LSQ (Kasa) nos vãos entre retas, com
  varredura monótona E **giro por ponto ≈ passo/r** — sem isso o arco **engolia bicos/vales**
  (caso estrela: canto curto desvia < tol do círculo grande) e as tangentes saíam erradas.
  Arco > 90° divide em 1 cúbica/90°.
- **Junções**: tangente da primitiva na âncora → reta↔filete G1 de graça; RETA manda sobre arco
  no nó compartilhado (é rígida; a média entortava a reta em S); primitivas coladas com
  tangentes discordando > ~25° = **canto vivo** → `_open_corner_gaps` recua as fronteiras e o
  canto vira trecho livre (legado). Âncoras de quadrante internas às primitivas suprimidas;
  saliências (`_protrusion_anchors`) são sagradas. `--min-dist` passa a reger só trechos livres.
- **Editor (`--edit`)**: shift+clique seleciona 2 nós (alça vermelha) e o botão **Line** remove
  os nós do caminho mais curto entre eles e traça a RETA (`straighten_between`); retas
  sobrevivem a mover/inserir/excluir (`remap_lines_insert`/`_delete`: inserir divide em 2 retas,
  excluir funde); duas retas consecutivas = canto legítimo (exceção deliberada ao G1, só manual).

Resultado (Pi 2, 2 fotos, **min-dist 10 = default**): 48 Béziers, contém 0.9999, folga
**+0.07/−0.05** (antes: 46 Béziers e +0.83/+0.19 em min-dist 7.5) — as retas não arqueiam p/
dentro e o pocket cola na peça. `--line-tol 0` reproduz o caminho legado exatamente. Suíte:
130 → **149** (`TestPrimitiveFit`, `TestStraightSegments`).

## Editor simétrico, régua, auto-nível e giro fino (plano 011)

Quatro features em volta do editor (`--edit`) e do nivelamento (hipóteses validadas com
experimentos descartáveis antes do código):

- **F1 — Simetria no editor:** descoberta estrutural — a saída de `symmetrize_beziers` JÁ nasce
  **pareada por índice** (`i ↔ (N−i)%N`, erro 0.000000 mm no thermpro; nós 0 e N/2 no eixo), então
  o espelhamento dispensa matching geométrico. Ops-par puras (`move/insert/delete/straighten_
  _sym`) preservam o invariante (provado em teste, inclusive sequências e re-canonicalização
  após excluir nó de eixo). O eixo vem FIXO da detecção (bbox da silhueta simetrizada — o cru
  fica ~0.2 mm fora do espelho real) e é desenhado pontilhado em coordenada de tela contínua.
- **F1b — Mirror ◀/▶:** o eixo é **arrastável** e o Mirror reconstrói um lado como espelho do
  outro (`mirror_contour`: nó de emenda na interseção exata; recusa >2 cruzamentos — mesmo
  critério do CLI; `snap_seam_nodes` evita degrau de 2(c′−c) ao re-parear em eixo movido).
  Conserta detecção que a sombra inflou de um lado e permite ligar simetria em contorno que veio
  sem `--symmetry` (a decisão original de desabilitar o toggle nesse caso foi revista).
- **F2 — Régua mm + cota:** faixas sup./esq. com ticks adaptativos ao zoom, cota W×H fora da
  bbox e no status (mover o eixo atualiza a largura ao vivo — correção guiada por paquímetro);
  toggle "Ruler".
- **F3 — `--level auto`:** auto-nível pelo **envelope** (`minAreaRect` + `snap90`), girando
  foto+máscara juntas ANTES da simetria, sem re-segmentar. Experimentos: minAreaRect recuperou
  exato os ângulos injetados e deu 0.00° no thermpro (baseline vira regressão); seleção de reta
  por comprimento tem viés (+1.4° — a reta mais longa era o topo inclinado), então a variante
  `bottom` (maior reta de baixo) ficou p/ fase 2. Faixa 0.2–7° + guarda de peça ~quadrada/redonda
  (disco recusa; quadrado passa pela reta ≥ 8 mm).
- **F4 — modo Rotate (decisão b, modo explícito):** linha-guia no cursor, cliques/rodinha giram
  **foto+nós juntos** em passos de 0.1° (0.05° com Shift) — nós no núcleo (`rotate_nodes`),
  foto por warpAffine **só do viewport** (transformada afim completa; custo constante). Girar
  desliga a simetria (v1); WYSIWYG: o editor passa a devolver `(cúbicas, foto girada)` e o
  overlay sai casado. Undo coalesce passos seguidos; Reset zera o ângulo.
- **Modo Pan (follow-up do F4, a pedido):** gêmeo do Rotate (toggle explícito, cliques/rodinha,
  linha-guia vertical), mas deslocando o **contorno + eixo de simetria** esquerda/direita em
  passos de 0.1 mm (0.05 com Shift) com a **foto parada** — corrige viés LATERAL uniforme da
  detecção (sombra que empurrou o contorno inteiro). Como nós e eixo andam o mesmo dx, o
  pareamento sobrevive por construção (`translate_nodes`, provado em teste) e a simetria **não**
  desliga. Exclusivo com o Rotate; Reset zera e devolve o eixo original da detecção.

Suíte: 149 → **188** (`TestSymmetryPairing`/`TestSymmetryOps`/`TestMirrorContour`/
`TestRotateNodes`/`TestTranslateNodes` no nível E; `TestAutoLevel` A/B; regressão C do
`--level` no thermpro).

## Contorno humilde — cordas entre trechos firmes (v0.12)

Origem: sessão de calibração do **TC1** (multi_tester, 2026-07-06) — carcaça **creme sobre
papel branco**, sem contraste; a curva **editada à mão** pelo usuário serviu de ground truth.
Medição-chave: só **17% da borda** da máscara estava apoiada num degrau real da imagem; os
outros 83% eram chute (halo de penumbra readmitida p/ FORA + mordida no bisel lavado p/ DENTRO,
invisível ao `contém`, que mede contra a própria máscara). Antes, a **v0.11** reservou um pacote
de correções "espertas" (registro 2-fotos por ZNCC de gradiente, faint-metal adaptativo,
watershed com guardas) — protótipos com ganho real, mas **rejeitados conscientemente** pelo
usuário: em vez de perseguir a segmentação perfeita, **admitir a incerteza** e degradar de forma
controlada.

A forma concreta é o estágio 2e do pipeline (`humble_rewrite` + flag `--humble`; mecanismo,
constantes e API em [design.md](design.md) §Pipeline 2e; operação no [manual](manual.md)
§`--humble`). Desvio único vs o spec do plano: o limiar de firmeza ganhou um **teto**
(`HUMBLE_GRAD_CAP` = 3× o piso) além do Otsu — sem ele o Otsu dividia a borda toda-forte do
thermpro e dava 43% firme (o gatilho dispararia numa foto boa); com o teto, 92%. A 2ª guarda
por saturação (§4 do plano, opcional) ficou de fora: a de textura bastou nos casos de teste.

Resultado no TC1 (receita da memória da skill, `--in2` com a mesma foto): **firme 9% → humilde
ativa**, pocket 73.77×97.68 (obj 73.62×97.50, contém 1.0000, 14 Béziers — as cordas viram RETAS
de verdade pelas primitivas v0.10), contra o halo de 2–5 mm folgado que antes exigia `--edit` à
mão; no protótipo da sessão, p95 +1.67 mm vs a curva editada, sem cortar a peça além de 1.3 mm.
Fotos boas não mudam nada (thermpro 92% firme, **byte-idêntico** por teste; trena 62%, Pi 94%).
Suíte: 190 → **200** (`TestHumbleRewrite`, nível B6).

## Ferramenta Measure + redesign da toolbar do editor

A pedido do usuário, o editor (`--edit`) ganhou **medição ponto-a-ponto em mm**: modo
**Measure** (toggle, exclusivo com Rotate/Pan) — 1º clique marca o ponto A, o preview segue o
cursor **travado no eixo dominante** do gesto (`measure_snap`: |dx|≥|dy| → horizontal, senão
vertical) e o 2º clique fecha; **Ctrl no 2º clique = ângulo livre**. A medição persiste **em
destaque** (laranja, estilo cota: ticks nas pontas, marca central em losango e rótulo `NN.NN mm`
com fundo escuro) até o **botão-direito** excluí-la (`nearest_measure`, distância ao segmento).
Medições são anotações — fora do Undo/Reset/Finalize. No mesmo passe, **redesign da toolbar**:
widgets `ttk` (visual nativo) em grupos com separadores (edição | simetria | vista), status bar
própria na base da janela e a **régua de bordas (F2) removida** — ficou só a **cota W×H verde**
(toggle renomeado `Ruler` → `Size`); a cota + o Measure cobrem o caso "bater com o paquímetro".
Suíte: 200 → **206** (`TestMeasureTool`, nível E).

## v0.13 — priors de geometria (`--describe` da skill → `--corner-radius`/`--shape`)

A skill `/ptoo` ganhou o campo **`--describe "texto"`**: o usuário declara em linguagem natural o
que **sabe** da peça ("é um retângulo com cantos arredondados de raio 5 mm") e o agente analisa a
descrição **no início** do laço, convertendo-a em priors estruturados p/ a CLI — a divisão de
inteligência é deliberada: NL no agente, flags determinísticos (testáveis) na CLI. Dois flags
novos: **`--corner-radius R`** — arco detectado com raio a ±max(1 mm, 20%) do prior é refit com
**raio fixo** (só o centro; pontas projetadas no círculo, só p/ fora): o canto sai com o raio
**medido pelo usuário**, não o estatístico da segmentação; **`--shape rect`** — o pocket é
**construído exato** (a receita "4 círculos nos cantos ligados por retas tangentes"): pose por
`minAreaRect`, 4 retas + 4 arcos de 90° em **8 Béziers**, W/H inflados o mínimo p/ conter (SDF
analítico), com salvaguardas de descrição errada (inflação > 2 mm ou vão modelo→peça > 5 mm →
WARNING + fallback genérico + `shape FALLBACK` nas métricas). Com o modelo, as rampas deixam de
reger o contorno — a calibração vira só segmentação. Suíte: 206 → **216** (`TestGeometryPriors`,
nível A).

## v0.14 — ajuste manual persistente (sidecar) + move em grupo no editor

O Rotate/Pan do editor deixou de ser descartável: é **calibração da foto** (peça torta na base,
viés lateral da segmentação) e agora **persiste** — ao Finalize o total acumulado é salvo num
sidecar `<foto>.adjust.json` (`save_adjust`) e **toda execução da CLI o reaplica**
(`load_adjust` → kwarg `adjust` de `generate_outline`): o giro roda foto+máscaras juntas pela
MESMA matriz da view do editor (`adjust_rot_affine`, fonte única) e o pan translada o contorno
extraído em mm exatos (overlay PNG desloca a máscara em px só p/ o desenho). O editor reabre já
com o ajuste aplicado (a view gira só o delta da sessão; Reset volta ao estado de abertura, não
a zero) e o **status bar mostra sempre** `rot ±x.xx°` / `pan ±x.xx mm` acumulados; zerar tudo e
Finalizar remove o sidecar. Motivação operacional: abrir a GUI já no **1º passe** da /ptoo (fixa
a calibração geométrica uma vez) além do último. Segunda feature: **move em grupo** — a seleção
por Shift+clique perdeu o teto de 2; com nós selecionados, um clique aplica a TODOS o Δ que leva
o **1º selecionado** ao ponto clicado (`move_selection`; com simetria ativa, cada par espelha o
mesmo Δ) — mover ponto a ponto sem arrastar. Suíte: 216 → **228** (`TestManualAdjust` nível F,
`TestMoveSelection` nível E).

## v0.15 — pins: pontos fixos do contorno marcados no editor

O sidecar de calibração ganhou o terceiro canal: **pins**. Todo nó que o usuário **reposiciona**
no `--edit` (arrasto ou move em grupo; com simetria, o par junto) fica marcado (alça magenta,
`self.pinned` remapeado por posição através de insert/delete/Line/Mirror — `remap_pinned`) e ao
Finalize as posições marcadas são salvas em `<foto>.adjust.json` junto do rot/pan
(`merge_pins`: pin novo a ≤ 1 mm do herdado o substitui). **Toda execução seguinte reaplica**:
`apply_pins` deforma a silhueta extraída — e a `sil_ref` do gate, senão o contém puniria a
correção pedida — p/ passar **exato** por cada pin, com decaimento cos² ao longo do arco
(`PIN_FALLOFF_MM = 6`), depois do rot+pan (pins vivem no referencial final). É o canal p/ o
usuário **corrigir a segmentação onde ela insiste em errar** (ex.: sombra que infla um trecho):
fixa a borda verdadeira uma vez e a correção vale nos passes seguintes da calibração. Pins
herdados aparecem como marcadores × (botão-direito exclui); Rotate/Pan os arrastam junto do
contorno; Rotate/Pan/Line/Mirror não marcam. Na /ptoo, o 1º passe com GUI agora fixa
rotate/pan **e os pontos fortes** do contorno. Suíte: 228 → **241** (`TestPins` nível F,
`TestPinnedTracking` nível E).

## v0.16 — Align V/H no editor

Dois botões novos na toolbar de edição: com **2+ nós selecionados** (shift+clique), **Align V**
alinha todos na vertical (mesmo x) e **Align H** na horizontal (mesmo y) — a coordenada de
referência é sempre a do **1º selecionado** (ele não se move; a outra coordenada de cada nó é
preservada). Com simetria ativa, cada nó vai ao alvo alinhado via op-par (o espelho recebe o
alinhamento espelhado). Como o Line, é reconstrução geométrica: **não marca pin**. Núcleo puro
`align_selection`; suíte: 241 → **246** (`TestAlignSelection` nível E).

## v0.17 — pins herdados viram nós on-curve no editor

Unificação do modelo de pins pedida pelo usuário: os pins **herdados** do sidecar deixam de ser
**marcadores × soltos** (que só marcavam a posição, com a curva passando por eles apenas porque o
pipeline já deformara a silhueta) e passam a abrir como **nós magenta on-curve normais** — a curva
passa **exato** por eles (nós são pontos de interpolação em `cubics_through_nodes`) e são
**arrastáveis/deletáveis** como um pin da sessão. Na abertura (e no Reset), `snap_pins_to_nodes`
(núcleo puro) converte cada pin: **encaixa** no nó existente a ≤ `PIN_SNAP_TOL_MM = 1 mm` (movido
exato p/ o pin) ou, se nenhum está perto, **insere** um nó novo no trecho mais próximo. Some o
conceito de `loose_pins`/`_delete_loose_pin_at`/`merge_pins` (obsoleto: não há mais herdado-vs-sessão
a fundir) e o rotate/pan especial dos loose pins (nós já giram/transladam junto). `adjust_state`
grava as posições atuais de **todos** os nós marcados; a idempotência se mantém (Finalize salva os
pins → próximo run `apply_pins` reproduz → o editor re-encaixa). Suíte: 246 → **248**
(`snap_pins_to_nodes` substitui os testes de `merge_pins` em `TestPinnedTracking`).

## v0.18 — hierarquia de nós e segmentos fixos (magenta = usuário, amarelo = calculado)

Fecha o buraco que os pins v0.15–v0.17 deixavam: o pin fixava um **ponto**, mas o **trecho**
entre dois pins seguia livre p/ o algoritmo reancorar/deformar — o usuário corrigia um setor
difícil à mão e a execução seguinte podia desfazer parte do trabalho. Agrupado numa hierarquia
única e simples de enunciar: **magenta = apontado pelo usuário (fixo), amarelo = calculado
(mutável)**, valendo p/ nós **e** trechos. Um trecho da curva cujas **duas pontas são pins** é
um **segmento fixo** (status **derivado** de `pinned`, sem marcação/estado paralelo): desenhado
em magenta, exportado ao Finalize p/ o sidecar (`segments`: pontas a/b, flag de reta e a
**cúbica da tela**) e reaplicado **literalmente** em toda execução. No pipeline: `apply_segments`
costura a geometria salva na silhueta (depois dos pins; arco escolhido por menor desvio, recusa
com aviso acima de `SEG_SPLICE_DEV_MM = 15 mm`) e `splice_fixed_cubics` — **último** passo de
`_fit_for_output`, depois de simetria/snap/humble — substitui o arco da curva ajustada pelas
cúbicas salvas bit a bit, com as emendas do lado calculado encaixadas exatas em a/b. No setor
protegido o algoritmo **não adiciona nó nem deforma nada**; ele termina só o resto do contorno.
É o pedido do usuário: **editar à mão um setor complexo e deixar o algoritmo trabalhar sem
destruir o que foi feito**. Detalhes de UX: retas do botão Line agora **persistem** entre
sessões (`line:true` no sidecar → `lines_from_segments` na reabertura, corrigindo a perda das
versões anteriores); nó inserido dentro de trecho fixo nasce pin (`pin_inserted_nodes` —
refinar ≠ rebaixar); excluir uma ponta devolve o trecho ao amarelo; **duplo-clique** num nó
alterna fixo↔calculado no lugar (`toggle_pin` — fixar/soltar sem reposicionar, complemento do
arrasto); a curva é colorida **por trecho** (magenta fixo / amarelo calculado); a **seleção**
saiu do vermelho p/ **ciano**
(`#00e5ff`), que colidia com a família magenta. Suíte: 248 → **264** (`TestFixedSegments`
nível F: sidecar, `apply_segments`, `splice_fixed_cubics`, proteção em `_fit_for_output`, e2e
thermpro; `TestFixedSegmentsEditor` nível E: derivação, export a→b, restauração de retas,
pin em inserção, `toggle_pin`).

## Migração OpenCV 4.13 → 5.0 (jul/2026)

Pin `opencv-python>=5.0,<6` (wheels seguem `cp37-abi3`, cobrindo o Python 3.14; numpy 2.5.1).
A suíte pegou **1 regressão real**: o `warpPerspective` do 5.0 arredonda ±1 nível de cinza
(~2% dos pixels), jitter de 1 px na borda da máscara — inócuo em si (bbox idêntica), mas
suficiente p/ o modo fiel escolher outra tolerância num trecho de fio-de-navalha: a seleção
só fiscalizava a penetração **p/ dentro**, e um arco longo podia passar com tolerância enorme
**balonando >1 mm p/ fora** — que o snap de bbox converte em **deslocamento** do contorno
sobre a peça (coverage 0,986 < 0,99; no 4.13 os trechos "sortudos" caíam do lado que não
deslocava — 0,993 por sorte). Correção de raiz: **teto de estufamento** no fiel
(`ANCHOR_OUT_CAP_MM = 0.25`, `_ceil_field` = distanceTransform do complemento) — fidelidade
passa a valer nos dois sentidos. Coverage subiu p/ **0,998 nas duas versões** (29–30 nós,
suavidade melhor). Suíte segue em **264**.

## Pendências / roadmap

- **Objeto claro/dessaturado** (peça metálica fosca) confundindo-se com o miolo branco: **em 2
  fotos, resolvido** pelo predicado faint-metal (v0.9); carcaça **creme≈papel** coberta pelo
  truque `--in2` com a MESMA foto + contorno humilde (v0.12), que remove o halo readmitido; em
  **foto única** segue o limite — uma variante de **base escura** resolveria.
- **Paralaxe pela altura** segue sem correção geral (nenhuma base resolve); hoje só mede e avisa.
  O modo 2 fotos com protocolo rígido (girar base+peça juntas, câmera no mesmo lugar) a torna
  simétrica e inócua p/ a fusão. Futuro: correção por altura conhecida.
- **Ondulação residual** em bordas de alto contraste (laranja↔bezel) — revisitar com **mais
  fotos-exemplo** antes de calibrar mais fino (evitar overfit).
- **Resíduos do `--shadow texture`**: a umbra caiu p/ ~0,5–1,5 mm com o watershed (v0.8); o
  **gume claro/especular** do corpo cinza ainda some no fundo claro (localização de borda).
- **Fusão 2-fotos:** canto sombrio nas DUAS fotos vira nick (~1,5 mm no Pi) — candidato a
  fechamento local guiado pelas bordas das duas máscaras; avaliar com mais peças.
- **Avisar** quando o contorno tocar a borda da imagem (peça grande/descentrada).
