# ptoo memory  (manter < 100 linhas; ao exceder, podar a linha de cache mais antiga)

## start = melhor aposta atual  (NÃO é fixo — é a média/consenso do cache, recalculado a cada update)
SEMPRE:      --shadow remove --max-nodes 300 --min-dist 0.5
CONDICIONAL: + --symmetry vertical|horizontal   (só se a peça tem eixo de espelho — avaliar no passe 1)
<!-- Este é o ponto de partida p/ um objeto NOVO. Para objeto já no cache, prefira a linha dele.
     Como o start é derivado (RECALCULAR sempre que mexer no cache abaixo):
     - numéricos (max-nodes, min-dist): MEDIANA das linhas do cache.
     - categóricos (shadow): o valor que venceu na MAIORIA das linhas → entra no SEMPRE.
     - symmetry: depende da peça (não generaliza) → fica como CONDICIONAL, nunca no SEMPRE.
     - amostra atual: n=1 objeto. Quanto mais objetos no cache, mais confiável o start. -->

## cache último-bom (≤5 linhas; evicta a mais antiga; 1 linha por objeto)
<!-- formato: - ~WxH mm | <params> | contém=0.NNNN clearance=+x/+y -->
- ~68x71 mm | --shadow remove --max-nodes 300 --min-dist 0.5 --symmetry vertical | contém=0.9982 clearance=-0.43/-0.07

## heurísticas (sintoma → delta)  — estável, não duplicar
- pocket folgado no BBOX (clearance grande) → saltar max-nodes p/ alto (200–300), NÃO ×2:
  o ×2 só aperta os lados (sobe 'contém'); a folga do bbox (cantos arredondados) só cede com
  muitos nós. min-dist→0.5
- não contém (AVISO / contém baixo) → ↑max-nodes
- serrilhado/escadinha → ↑smooth-mm (+4)
- borda arredondada some / segmentação come a peça → --shadow remove
- SEMPRE avaliar simetria no passe 1 (pelo overview): se a peça tem eixo de espelho claro,
  já ligar --symmetry vertical|horizontal (eixo do objeto). Limpa ruído dos lados e SOBE
  'contém' (ex.: thermpro 0.9980→0.9982). Não usar em peça assimétrica (distorce)
- bico/canto vivo de 90° → ↑min-radius (+0.5)
- vermelho vaza p/ fora (fundo) ou peça clara some no branco → limite de
  segmentação; não há flag que resolva → sinalizar p/ --debug

## notas de aceite
- 'contém' tem teto prático ~0.998 (POCKET_EPS deixa a curva tocar/cortar ≤0.5mm). Não exigir
  0.999. Snug = clearance perto de 0 (até levemente negativo) com 'contém' ~0.998. A folga real
  vem do --clearance aplicado a jusante.
