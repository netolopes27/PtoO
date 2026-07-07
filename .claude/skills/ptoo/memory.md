# ptoo memory — manter < 100 linhas. Regras de atualização: SKILL.md §Depois do laço.
# Gate/ranking/rampas: SKILL.md (fonte única). Sintoma → flag: docs/manual.md §6.

## start = melhor aposta p/ objeto NOVO (derivado do runs.tsv via scripts/derive_start.py, n=10
## vencedores; recalcular a cada update)
SEMPRE:      --shadow remove --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2
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
- ~67.62x70.88 mm | --shadow remove --min-dist 3 --smooth-mm 2.5 --pocket-eps 0 --symmetry vertical --mask-smooth-mm 2 | contém=0.9999 clearance=+0.05/+0.07 | thermpro (cromático, simétrico); md insensível 1.5–3 (curva idêntica, 24 nós)
- ~59.62x60.75 mm | --shadow remove --min-dist 1 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 | contém=1.0000 clearance=+0.01/-0.04 | trena azul; assimétrica (aba lateral) → SEM symmetry
- ~90.00x58.75 mm | --shadow remove --min-dist 10 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps --shape rect --corner-radius 3 --in2 <foto2> | contém=1.0000 clearance=+0.07/+0.03 | pi_up retilínea DECLARADA (v0.13): modelo rect r=3 (infl 0 = r real), 8 Béziers; pós-edit o usuário aperta p/ 88.38x59.14 (contém 0.9949 — a máscara superestima W pela paralaxe dos conectores)
- ~65.12x65.50 mm | --shadow texture --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps | contém=1.0000 clearance=-0.21/-0.24 | trena CINZA-neutra, sombra projetada, luz difusa; SEM symmetry; sem keep-bumps o gancho some (contém 0.9968 + aviso)
- ~73.62x97.50 mm | --shadow remove --min-dist 10 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps --in2 <MESMA foto> | contém=1.0000 clearance=+0.14/+0.18 | tester TC1 creme≈papel; humilde AUTO ativou (firme 9%) e removeu o halo que antes exigia --edit (curva à mão dava 72.55x93.72); 14 Béziers

## heurísticas (fatos medidos ALÉM do manual §6; não duplicar manual nem SKILL)
- A rampa min-dist fecha onde a FORMA manda: contorno orgânico/cantos arredondados fecha baixo
  (~1–1.5); PLACA retangular fecha alto (7.5–10; com primitivas v0.10, o default 10 já cola —
  folga +0.07 no Pi). Se o 1º passe JÁ cruza o gate, SUBA min-dist (menos nós) em vez de descer.
- v0.10 primitivas (--line-tol/--arc-tol 0.3, LIGADO por default): aresta reta vira RETA exata e
  canto vira ARCO → min-dist rege só trechos LIVRES. Facetou curva gentil ou perdeu aresta →
  --line-tol ↓0.2 (conservador) / ↑0.5 (agressivo). --line-tol 0 = legado puro (A/B barato).
  A rampa min-dist tem PLATÔS (thermpro: 1.5 e 3 → paths idênticos): passo pequeno pode não
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
  = raio real MENOR → desça --corner-radius até infl≈0 (Pi: r=5→infl .42, r=3→infl 0; o raio
  real "se mede" pela inflação). O modelo cruza o gate POR CONSTRUÇÃO mas pode sair FOLGADO:
  saliência real fora do retângulo (soquete do TC1) entorta o minAreaRect (~2°) → folga
  +2.8/+2.1 vs +0.14 do genérico — SEMPRE compare a folga com o melhor passe genérico antes de
  declarar o modelo vencedor (exceção explícita à regra "menos nós vence"). O modelo NÃO conserta
  segmentação ruim: Pi em foto ÚNICA (sombra dura sem --in2) deforma a máscara → vão 9.6 →
  FALLBACK correto; a máscara precisa da MESMA qualidade do genérico.
- v0.12 CONTORNO HUMILDE: CLI avisou "só NN% da borda tem apoio visual" → o humilde JÁ ativou
  (cordas entre trechos firmes; métrica `firme NN%`). Conferir os trechos LARANJA (flags) no
  overlay ANTES de mexer em rampas — o défice ali não é densidade, é borda incerta; acabamento
  pontual no --edit. Halo localizado com borda boa no resto → --humble on. NÃO combine com
  --faithful/--tol-fit (ignorado). Peça LISA de borda curva sem contraste: risco da corda
  raspar bojo real (guarda de textura não vê) → conferir no zoom.
