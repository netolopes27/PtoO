# ptoo memory  (manter < 100 linhas; ao exceder, podar a linha de cache mais antiga)

## start = melhor aposta atual  (NÃO é fixo — é a média/consenso do cache, recalculado a cada update)
SEMPRE:      --shadow remove --min-dist 10 --symmetry vertical
CONDICIONAL: desligar --symmetry em peça assimétrica (distorce); trocar p/ horizontal se o eixo for outro
<!-- Semente inicial definida pelo usuário; cache VAZIO (n=0, skill ainda não rodada). Ponto de
     partida p/ objeto NOVO; quando houver linha de cache do objeto, prefira a linha dele.
     --min-dist é a ALAVANCA de densidade (não existe --max-nodes): RAMPA de CIMA p/ BAIXO —
     comece em 10 e BAIXE (10→4→2→1→0.5; bissecte) até contém≥0.9999; pare no MAIOR que cruza
     (maior min-dist = menos nós = melhor). smooth-mm: sem valor na semente → usa o default do CLI
     (8); baixe (→2) só como lever fino se a rampa de min-dist encostar mas não cruzar.
     Demais derivados (RECALCULAR ao mexer no cache, quando houver linhas):
     - numéricos (min-dist, smooth-mm): MEDIANA das linhas do cache.
     - categóricos (shadow): o valor que venceu na MAIORIA → entra no SEMPRE.
     - symmetry: por-peça; avaliar no passe 1 (a semente liga vertical por escolha do usuário). -->

## cache último-bom (≤5 linhas; evicta a mais antiga; 1 linha por objeto)
<!-- formato: - ~WxH mm | <params> | contém=0.NNNN clearance=+x/+y -->
<!-- (vazio — nenhum objeto calibrado ainda) -->

## heurísticas (sintoma → delta)  — estável, não duplicar
- contém < 0.9999 (LEVER PRIMÁRIO = RAMPA de --min-dist, de CIMA p/ BAIXO) → ↓min-dist (10→4→2→1→0.5,
  bissecte) até cruzar 0.9999; pare no MAIOR que cruza (maior min-dist = menos nós = melhor).
  NÃO existe --max-nodes: a densidade emerge só do espaçamento. CONTRA-INTUITIVO: min-dist GRANDE
  (poucos nós) NÃO contém mais — âncoras esparsas fazem os Béziers longos arquearem p/ dentro nos
  cantos, cortando a peça; daí min-dist grande = pocket frouxo E contém travado ~0.998.
- smooth-mm é o LEVER FINO do contém (não o primário): baixar (8→2) aproxima o piso da silhueta
  crua e raspa os últimos 0.0x quando a rampa de min-dist encosta mas não cruza. Fique em ~2 (≲1
  serrilha).
- pocket-eps (penetração tolerada, default 0.5) quase não mexe no contém (eps 0.5→0 ≈ +0.0001).
  Use só p/ ajuste fino do último 0.0x quando a curva encosta/corta de leve.
- serrilhado/escadinha → ↑smooth-mm (+1..2). CONFLITA com o contém: ache o equilíbrio (smooth ~2).
- borda arredondada some / segmentação come a peça → --shadow remove
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
- DESEMPATE: entre resultados que batem 0.9999, vence MENOS nós (Béziers) = MAIOR --min-dist;
  empate → menor clearance.
