# ptoo memory — manter < 100 linhas. Regras de atualização: SKILL.md §Depois do laço.
# Gate/ranking/rampas: SKILL.md (fonte única). Sintoma → flag: docs/manual.md §6.

## start = melhor aposta p/ objeto NOVO (derivado do cache, n=4; recalcular a cada update)
SEMPRE:      --shadow remove --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2
CONDICIONAL: --symmetry vertical|horizontal — SÓ com eixo de espelho claro; NUNCA em peça
             assimétrica; com sombra vazando, a simetria UNE o vazamento p/ os dois lados (piora)
CONDICIONAL: --mask-smooth-keep-bumps — quando o CLI avisar "removeu uma saliência convexa"
             (feature real, ex.: gancho da trena)
CONDICIONAL: --shadow texture — corpo CINZA-NEUTRO (sem croma) COM sombra projetada; SEM sombra
             projetada use ↑--val-frac ~0.68 (val-frac alto + sombra projetada VAZA)
CONDICIONAL: peça RETILÍNEA (placa) → começar a rampa min-dist NO DEFAULT 10 (v0.10; ver heurísticas)

## cache último-bom (≤5 linhas; 1 linha por objeto; evicta a mais antiga)
<!-- formato: - ~WxH mm | <params> | contém=… clearance=… | nota curta -->
- ~67.62x70.88 mm | --shadow remove --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --symmetry vertical --mask-smooth-mm 2 | contém=0.9999 clearance=-0.06/+0.01 | thermpro (cromático, simétrico)
- ~59.62x60.75 mm | --shadow remove --min-dist 1 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 | contém=1.0000 clearance=+0.01/-0.04 | trena azul; assimétrica (aba lateral) → SEM symmetry
- ~90.00x58.75 mm | --shadow remove --min-dist 10 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps --in2 <foto2> | contém=0.9999 clearance=+0.07/-0.05 | Raspberry Pi 2, 2 FOTOS luz oposta; retilínea → md10 DEFAULT já cola (48 nós, v0.10); A/B legado: --line-tol 0 (md7.5, 46 nós, folga +0.83)
- ~65.12x65.50 mm | --shadow texture --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 --mask-smooth-keep-bumps | contém=1.0000 clearance=-0.21/-0.24 | trena CINZA-neutra, sombra projetada, luz difusa; SEM symmetry; sem keep-bumps o gancho some (contém 0.9968 + aviso)

## heurísticas (fatos medidos ALÉM do manual §6; não duplicar manual nem SKILL)
- A rampa min-dist fecha onde a FORMA manda: contorno orgânico/cantos arredondados fecha baixo
  (~1–1.5); PLACA retangular fecha alto (7.5–10; com primitivas v0.10, o default 10 já cola —
  folga +0.07 no Pi). Se o 1º passe JÁ cruza o gate, SUBA min-dist (menos nós) em vez de descer.
- v0.10 primitivas (--line-tol/--arc-tol 0.3, LIGADO por default): aresta reta vira RETA exata e
  canto vira ARCO → min-dist rege só trechos LIVRES. Facetou curva gentil ou perdeu aresta →
  --line-tol ↓0.2 (conservador) / ↑0.5 (agressivo). --line-tol 0 = legado puro (A/B barato).
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
- Vermelho vaza p/ o fundo ou peça clara some no branco (foto única) → limite de segmentação, sem
  flag que resolva → anotar p/ o --debug.
