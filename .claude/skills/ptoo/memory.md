# ptoo memory  (manter < 100 linhas; ao exceder, podar a linha de cache mais antiga)

## start = melhor aposta atual  (NÃO é fixo — é a média/consenso do cache, recalculado a cada update)
SEMPRE:      --shadow remove --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2
CONDICIONAL: --symmetry vertical|horizontal (eixo do objeto); SÓ em peça com eixo de espelho claro; desligar em assimétrica (trena é assimétrica → sem symmetry; em foto com sombra a simetria UNE o vazamento p/ os dois lados → piora)
CONDICIONAL: --shadow texture p/ CORPO CINZA-NEUTRO (sem croma) COM SOMBRA PROJETADA (v0.5): valor pega o corpo, textura (Otsu adaptativo) recorta a sombra lisa-e-clara; funciona até em fundo de papel cromático. Trena cinza luz difusa: obj 76→64.5mm (some o balão de sombra), contém 1.0000. Fallback antigo (--val-frac ~0.68 --shadow OFF) só onde NÃO há sombra projetada — ele VAZA a sombra. Sombra de CONTATO (escura) ainda não é recortada pelo texture (pendência v0.6)
<!-- cache ATUALIZADO (n=3). Ponto de partida p/ objeto NOVO; quando houver
     linha de cache do objeto, prefira a linha dele.
     TODAS as rampas são ADAPTATIVAS com INVERSÃO: direção padrão ↓, enquanto melhorar continue;
     parou de melhorar → inverta p/ ↑; piorou na invertida → volte ao melhor e próxima rampa.
     "Melhor" = cruza 0.9999 vence não-cruza; entre cruzas, menos nós vence; entre não-cruzas,
     maior contém vence; empate → menor clearance.
     1ª --min-dist (piso 1, teto ~10)  2ª --smooth-mm (piso ~2, teto ~10)  3ª --pocket-eps (piso 0,
     teto 0.5). Se esgotou uma rampa, passe p/ a seguinte.
     Demais derivados (RECALCULAR ao mexer no cache):
     - numéricos (min-dist, smooth-mm, pocket-eps): MEDIANA das linhas do cache.
     - categóricos (shadow): o valor que venceu na MAIORIA → entra no SEMPRE.
     - symmetry: por-peça; avaliar no passe 1. -->

## cache último-bom (≤5 linhas; evicta a mais antiga; 1 linha por objeto)
<!-- formato: - ~WxH mm | <params> | contém=0.NNNN clearance=+x/+y -->
- ~67.62x70.88 mm | --shadow remove --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --symmetry vertical --mask-smooth-mm 2 | contém=0.9999 clearance=-0.06/+0.01
- ~59.62x60.75 mm | --shadow remove --min-dist 1 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 (trena azul, assimétrica: aba lateral → SEM symmetry) | contém=1.0000 clearance=+0.01/-0.04
- ~64.50x60.50 mm | --shadow texture --min-dist 1.5 --smooth-mm 2.5 --pocket-eps 0 --mask-smooth-mm 2 (trena CINZA-neutra + sombra projetada, luz difusa: texture recorta a sombra; SEM symmetry; md1.5=135 nós cruza 0.9999, md1=180 nós 1.0000 → desempate p/ md1.5) | contém=0.9999 clearance=+0.00/+0.01

## heurísticas (sintoma → delta)  — estável, não duplicar
- RAMPAS ADAPTATIVAS com INVERSÃO: 1ª --min-dist (piso 1, teto ~10) → 2ª --smooth-mm (piso ~2,
  teto ~10) → 3ª --pocket-eps (piso 0, teto 0.5). Em cada rampa, a partir do start/cache:
  • Direção padrão ↓ (baixar parâmetro → tipicamente sobe contém). Continue enquanto melhorar.
  • Parou de melhorar → inverta a direção (↑) a partir do start.
  • Piorou também na invertida → volte ao melhor encontrado, rampa esgotou → próxima.
  "Melhor" = cruza 0.9999 > não-cruza; entre cruzas: menos nós; entre não-cruzas: maior contém.
  CONTRA-INTUITIVO: min-dist GRANDE = âncoras esparsas → Béziers longos arqueiam p/ dentro nos
  cantos → contém MENOR (pocket frouxo E contém ~0.998).
- smooth-mm: baixar aproxima o piso da silhueta crua e sobe contém; subir tira serrilhado. Abaixo
  de ~2 reintroduz serrilha.
- pocket-eps: baixar reduz penetração tolerada e sobe contém (~+0.0001–0.0003/degrau). Degraus
  típicos: 0.5, 0.3, 0.1, 0.
- serrilhado/escadinha → ↑smooth-mm (+1..2). CONFLITA com o contém: ache o equilíbrio (smooth ~2).
- ondulações/saliências na borda PRETA (baixo contraste, mesmo com contém ok) → --mask-smooth-mm
  ~1.5-2: regulariza a SILHUETA na fonte, ORTOGONAL ao contém (não é rampa; não mexe no gate).
- borda arredondada some / segmentação come a peça → --shadow remove
- CORPO CINZA-NEUTRO (só o clipe/botão segmenta; obj sai pequeno demais) → COM sombra projetada use
  --shadow texture (recorta a sombra pela textura, Otsu adaptativo); SEM sombra, ↑--val-frac (~0.68).
  NÃO combine val-frac alto + shadow OFF se houver sombra projetada: ela vaza no mesmo brilho.
- SEMPRE avaliar simetria no passe 1 (pelo overview): se a peça tem eixo de espelho claro, ligar
  --symmetry vertical|horizontal (eixo do objeto). Limpa ruído e sobe contém. NÃO usar em peça
  assimétrica (distorce).
- bico/canto vivo de 90° → ↑min-radius (+0.5)
- contorno EXATO (não pocket, bbox = objeto) → --faithful (substitui o antigo --max-nodes 0)
- vermelho vaza p/ fora (fundo) ou peça clara some no branco → limite de segmentação; não há flag
  que resolva → sinalizar p/ --debug
- DEPOIS de cruzar o gate, explorar os demais flags (1/passe) rumo a "quase default" da peça; ler
  docs/manual.md p/ o efeito completo de cada um.

## notas de aceite
- ALVO RÍGIDO: só parar com contém ≥ 0.9999 (gate mantido). A folga real vem do --clearance a jusante.
- DESEMPATE: entre resultados que batem 0.9999, vence MENOS nós (Béziers) = MAIOR valor dos
  parâmetros de rampa que ainda cruza; empate → menor clearance.
