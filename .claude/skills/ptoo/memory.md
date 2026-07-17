# ptoo memory — manter < 100 linhas. Regras de atualização: SKILL.md §Depois do laço.
# Gate/ranking/rampas: SKILL.md (fonte única). Sintoma → flag: docs/manual.md §6.

## start = melhor aposta p/ objeto NOVO (derivado do runs.tsv via scripts/derive_start.py, n=15
## vencedores; recalcular a cada update)
SEMPRE:      --shadow remove --min-dist 2 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2
CONDICIONAL: --symmetry vertical|horizontal — SÓ com eixo de espelho claro; NUNCA em peça
             assimétrica; com sombra vazando, a simetria UNE o vazamento p/ os dois lados (piora)
CONDICIONAL: --mask-smooth-keep-bumps — quando o CLI avisar "removeu uma saliência convexa"
             (feature real, ex.: gancho da trena)
CONDICIONAL: --shadow texture — corpo CINZA-NEUTRO (sem croma) COM sombra projetada; SEM sombra
             projetada use ↑--val-frac ~0.68 (val-frac alto + sombra projetada VAZA)
CONDICIONAL: peça RETILÍNEA (placa) → começar a rampa min-dist NO DEFAULT 10 (v0.10; ver heurísticas)

## cache último-bom (≤5 linhas; 1 linha por objeto; evicta a mais antiga; histórico COMPLETO
## por-passe fica no runs.tsv — nada morre na evicção)
<!-- formato: - ~WxH mm | <params> | contém=… clearance=… | nota curta -->
- ~68.69x70.59 mm | --shadow remove --min-dist 4 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --symmetry vertical | contém=0.9945 clearance=- | thermpro (amostra); sidecar rot -0.60 · pan +0.30 · 21 pins + 20 trechos fixos; --edit WYSIWYG definitivo 30 Béziers (contém medido vs máscara — edit manual vale mais); platô md 2–4
- ~77.62x140.07 mm | --val-frac 0.75 --shadow remove --min-dist 2 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps | contém=0.9992 clearance=-/+ | zoerax (alicate); ajuste fino intenso refinado (rot -1.9, 18 pins, 16 trechos fixos); contém 0.9992 definitivo; 66 Béziers
- ~90.53x58.98 mm | --in2 pi_down --shadow remove --min-dist 10 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps --corner-radius 3 | contém=1.0000 clearance=+0.00/+0.00 | Raspberry Pi 2B; 2 fotos; GENÉRICO; 34 pins + 34 TRECHOS FIXOS = contorno 100% fixo (sem amarelo); rampas sem efeito; --edit WYSIWYG 34 Béziers contém 1.0000 definitivo; firme 94%

- ~123.00x78.00 mm | --shadow remove --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --val-frac 0.68 --shape rect --corner-radius 7 | contém=1.0000 clearance=+0.10/+0.52 | case_usb; modelo rect DECLARADO; infl 0 (raio real = 7); contorno perfeito de 8 Beziers
- ~159.62x34.75 mm | --shadow remove --min-dist 2 --smooth-mm 2.0 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps | contém=0.9156 clearance=- | one_blade; ajuste manual extenso rot +1.70 · 35 pins · 35 trechos fixos; contém caiu p/ 0.9156 definitivo; 35 Béziers

## heurísticas (fatos medidos ALÉM do manual §6; não duplicar manual nem SKILL)
- A rampa min-dist fecha onde a FORMA manda: contorno orgânico/cantos arredondados fecha baixo
  (~1–1.5); PLACA retangular fecha alto (7.5–10; com primitivas v0.10, o default 10 já cola).
  Se o 1º passe JÁ cruza o gate, SUBA min-dist (menos nós) em vez de descer.
- v0.10 primitivas (--line-tol/--arc-tol 0.3, LIGADO por default): aresta reta vira RETA exata e
  canto vira ARCO → min-dist rege só trechos LIVRES. Facetou curva gentil ou perdeu aresta →
  --line-tol ↓0.2 (conservador) / ↑0.5 (agressivo). --line-tol 0 = legado puro (A/B barato).
  A rampa min-dist tem PLATÔS (thermpro: 2 e 4 → métricas idênticas): passo pequeno pode não
  mudar NADA — dobre o valor no passo ↑ e cheque nós/paths antes de gastar outro passe.
- v0.7: contém é medido contra a silhueta PRÉ-mask-smooth com tolerância 0.3 mm de profundidade —
  contém de sessões < v0.7 NÃO é comparável. AVISO "removeu uma saliência convexa" → ligar
  --mask-smooth-keep-bumps e NÃO mexer nas rampas (o défice não é densidade). Espigões finos
  (recuo ≥0.3, boca ≤3 mm) são preservados do smooth-mm automaticamente.
- --mask-smooth-mm ~1.5–2 p/ ondulação de borda PRETA de baixo contraste: regulariza a silhueta
  na FONTE, ortogonal ao contém — não é rampa, não mexa nas rampas por causa disto.
- v0.8: no --shadow texture o watershed embutido expulsa a UMBRA; resíduo típico ~0.5–1.5 mm
  (antes vazava ~4–5 mm) — verificar no zoom, não nas métricas.
- 2 FOTOS (--in2), p/ sombra dura (sol) OU metal claro ≈ papel: registro roda nas máscaras
  LIMPAS (IoU×ZNCC); AVISO "sombras caem do MESMO lado" → refotografar com luz realmente oposta.
  CONFERIR NO ZOOM se conectores/metal ficaram DENTRO do contorno: baía na máscara NÃO derruba o
  contém (ele mede contra a própria máscara — só o zoom pega). --fuse-grow só p/ resíduo perto da
  bissetriz das sombras.
- Vermelho vaza p/ o fundo (foto única) → limite de segmentação, sem flag que resolva → anotar
  p/ o --debug. Peça clara que some no branco: ver o truque --in2 mesma foto + humilde (abaixo).
- REGISTRO 2-fotos pode travar na família 90° (score ~0.24) se a peça girou ~180° EM RELAÇÃO À BASE
  entre as fotos (protocolo violado: girar base+peça JUNTAS). Sintomas: obj W×H TRANSPOSTO, lóbulos
  gigantes no 02g_fuse_split, fundo do overlay girado vs contorno. Sem flag; refotografar. (TC1)
- Truque p/ peça CLARA (creme≈papel) sem fusão utilizável: --in2 com a MESMA foto → registro
  identidade + faint-metal ON (única via que segmenta o corpo claro). O halo de sombra que o
  faint readmite é removido pelo humilde (v0.12, abaixo) — não precisa mais do --edit p/ isso.
  Prefira a foto de luz MAIS direcional (menos penumbra = mais borda firme p/ ancorar cordas).
- v0.13 --shape rect (peça DECLARADA retângulo via --describe): `infl` > 0 com o raio declarado
  = raio real MENOR → desça --corner-radius até infl≈0 (o raio real "se mede" pela inflação:
  case_usb r=3→infl>0, r=7→infl 0). O modelo cruza o gate POR CONSTRUÇÃO mas pode sair FOLGADO:
  saliência real fora do retângulo (soquete do TC1) entorta o minAreaRect (~2°) → folga
  +2.8/+2.1 vs +0.14 do genérico — SEMPRE compare a folga com o melhor passe genérico antes de
  declarar o modelo vencedor (exceção explícita à regra "menos nós vence"). O modelo NÃO conserta
  segmentação ruim: placa em foto ÚNICA com sombra dura (sem --in2) deforma a máscara → vão >
  teto → FALLBACK correto; a máscara precisa da MESMA qualidade do genérico.
- PLACA (PCB) com CONECTORES SALIENTES (RJ45/USB/HDMI metal claro que sai do retângulo, ex.: Raspberry
  Pi): caminho GENÉRICO, NÃO --shape rect (o retângulo excluiria ou inflaria/torceria p/ os conectores,
  como o soquete do TC1). --in2 (2 fotos) recupera o metal claro ≈ papel; --mask-smooth-mm come CADA
  bump de conector (AVISO "saliência convexa") → --mask-smooth-keep-bumps é OBRIGATÓRIO. min-dist 10
  fecha SEM pins (Pi: 0.9999 folga +0.07); COM pins o ótimo da rampa depende da DENSIDADE de pins:
  17 pins → md10 arqueia p/ dentro (folga X NEG 0.9995), ótimo ~5 (5→0.9998; 2.5→0.9996); 9 pins →
  md10 NÃO arqueia (folga +0.31, 0.9999, 48 Bez) e VENCE (menos nós). Menos pins = corda mais livre
  = tolera min-dist maior. --corner-radius R só cantos REAIS.
- v0.18 SEGMENTOS FIXOS (hierarquia magenta/amarelo): no --edit, trecho com as DUAS pontas
  pinned = FIXO (magenta), salvo LITERAL no sidecar (geometria + reta/curva) e reaplicado
  intocado em todo passe; o resto (amarelo) é do algoritmo. Duplo-clique num nó alterna
  fixo↔calculado sem movê-lo (fixa no lugar / solta p/ recalcular). Consequência p/ o calibrador:
  onde há trecho fixo, --min-dist/--smooth-mm/--pocket-eps NÃO mudam nada — o campo de trabalho
  é só o amarelo. Status/stdout mostram `N pins · M trechos fixos`. AVISO "segmento fixo NÃO
  costurado" (detecção mudou > 15 mm entre passes) → NÃO compensar por param; refazer o trecho
  no --edit. Nunca re-rodar sem --edit após um edit com trechos fixos: o amarelo é recomputado
  e sobrescreve a curva finalizada.
- v0.12 CONTORNO HUMILDE: CLI avisou "só NN% da borda tem apoio visual" → o humilde JÁ ativou
  (cordas entre trechos firmes; métrica `firme NN%`). Conferir os trechos LARANJA (flags) no
  overlay ANTES de mexer em rampas — o défice ali não é densidade, é borda incerta; acabamento
  pontual no --edit. Halo localizado com borda boa no resto → --humble on. NÃO combine com
  --faithful/--tol-fit (ignorado). Peça LISA de borda curva sem contraste: risco da corda
  raspar bojo real (guarda de textura não vê) → conferir no zoom.
