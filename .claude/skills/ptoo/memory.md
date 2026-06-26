# ptoo memory  (manter < 100 linhas; ao exceder, podar a linha de cache mais antiga)

## start = melhor aposta atual  (NÃO é fixo — é a média/consenso do cache, recalculado a cada update)
SEMPRE:      --shadow remove --min-dist 0.5 --smooth-mm 2   + RAMPA de --max-nodes (4↑, ver abaixo)
CONDICIONAL: + --symmetry vertical|horizontal   (só se a peça tem eixo de espelho — avaliar no passe 1)
<!-- Ponto de partida p/ objeto NOVO. Para objeto já no cache, prefira a linha dele.
     --max-nodes NÃO entra como valor fixo: é uma RAMPA de baixo p/ cima (comece em 4, dobre,
     bissecte) buscando o MENOR nº de nós que bate contém≥0.9999. O cache só diz onde a rampa
     costuma parar (encurta a busca). Objetivo: MENOS nós é melhor.
     Demais derivados (RECALCULAR ao mexer no cache):
     - numéricos (min-dist, smooth-mm): MEDIANA das linhas do cache.
     - categóricos (shadow): o valor que venceu na MAIORIA → entra no SEMPRE.
     - symmetry: depende da peça → CONDICIONAL, nunca no SEMPRE.
     - amostra atual: n=1 objeto. Mais objetos = start mais confiável. -->

## cache último-bom (≤5 linhas; evicta a mais antiga; 1 linha por objeto)
<!-- formato: - ~WxH mm | <params> | contém=0.NNNN clearance=+x/+y -->
- ~68x71 mm | --shadow remove --max-nodes 288 --min-dist 0.5 --smooth-mm 2 --symmetry vertical | contém=0.9999 clearance=-0.18/-0.00 (rampa: 4→0.9990; 128→0.9977; 256→0.9998; 272→0.9998; 288=menor que cruza 0.9999)

## heurísticas (sintoma → delta)  — estável, não duplicar
- contém < 0.9999 (LEVER PRIMÁRIO = RAMPA de max-nodes, de baixo p/ cima) → ↑max-nodes (4→8→…
  dobrando, depois bissecte) até cruzar 0.9999; pare no MENOR que cruza (menos nós é melhor).
  CONTRA-INTUITIVO: poucos nós NÃO contém mais — âncoras esparsas fazem os Béziers longos
  arquearem p/ dentro nos cantos arredondados, cortando a peça; daí poucos nós = pocket frouxo
  (+2mm) E contém travado em ~0.998. Medido na thermpro: <128 nunca cruza; 288 = menor que bate.
- smooth-mm é o LEVER FINO do contém (não o primário): baixar (8→2) aproxima o piso da silhueta
  crua e raspa os últimos 0.0x quando a rampa de nós encosta mas não cruza. Fique em ~2 (≲1
  serrilha). min-dist→0.5 adensa âncoras (ajuda a rampa cruzar com menos nós).
- pocket-eps (penetração tolerada, default 0.5) quase não mexe no contém (eps 0.5→0 ≈ +0.0001).
  Use só p/ ajuste fino do último 0.0x quando a curva encosta/corta de leve.
- serrilhado/escadinha → ↑smooth-mm (+1..2). CONFLITA com o contém: ache o equilíbrio (smooth ~2).
- borda arredondada some / segmentação come a peça → --shadow remove
- SEMPRE avaliar simetria no passe 1 (pelo overview): se a peça tem eixo de espelho claro,
  já ligar --symmetry vertical|horizontal (eixo do objeto). Limpa ruído dos lados e sobe contém.
  Não usar em peça assimétrica (distorce)
- bico/canto vivo de 90° → ↑min-radius (+0.5)
- vermelho vaza p/ fora (fundo) ou peça clara some no branco → limite de
  segmentação; não há flag que resolva → sinalizar p/ --debug

## notas de aceite
- ALVO RÍGIDO: só parar com contém ≥ 0.9999 (gate mantido). O ~0.998 que aparece com poucos nós
  NÃO é teto do tool — é só a rampa ainda baixa; subindo max-nodes (até ~288 na thermpro) cruza
  0.9999 com contorno suave (smooth ~2). A folga real vem do --clearance a jusante.
- DESEMPATE: entre resultados que batem 0.9999, vence MENOS nós (Béziers); empate → menor
  clearance. (Antes era menor clearance primeiro — invertido a pedido do usuário.)
