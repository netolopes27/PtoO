---
name: ptoo
description: >-
  Calibra iterativamente a CLI photo_to_outline.py deste repo a partir de uma foto, mirando um
  POCKET de encaixe justo. Use quando o usuário rodar /ptoo <foto.jpg> --pass N [--debug], pedir
  para "gerar/calibrar o contorno/SVG/pocket a partir de uma foto", ou ajustar os parâmetros do
  photo-to-outline. Roda a CLI, inspeciona o contorno com zoom sobre a foto, recalibra os
  parâmetros em até N tentativas e mantém uma memória pequena.
---

# Skill /ptoo — calibrador iterativo do photo_to_outline

Automatiza o laço "rodar → olhar o overlay → ajustar flag → repetir" da CLI `photo_to_outline.py`,
mirando um **pocket que contém a peça**: o critério de aceite é `contém a peça` ≥ **0.9999**.
Só pare cedo se atingir 0.9999 (ou se os passes esgotarem) — **nunca** pare por "aceitável"
abaixo disso. Entre resultados que batem 0.9999, prefira o de **menos nós** (pocket mais simples) —
o que, com a densidade ditada por `--min-dist`, significa o **MAIOR `--min-dist` que ainda cruza**;
clearance é só desempate secundário. A folga real vem do `--clearance` aplicado a jusante. Limite
de tentativas = `--pass N`.

> **Todas as rampas são adaptativas com INVERSÃO de direção.** A partir do cache/start, ande numa
> direção enquanto o resultado melhorar; quando parar de melhorar, **inverta a direção**; se piorar
> também na direção invertida, **volte ao melhor encontrado** e passe p/ a próxima rampa.
>
> **"Melhor" = composto:** (1) cruza `contém ≥ 0.9999` vence quem não cruza; (2) entre quem cruza,
> **menos nós** (Béziers) vence; (3) entre quem não cruza, **maior contém** vence; (4) empate
> final → menor clearance.
>
> **Estratégia por rampa:**
> 1. Rode com o valor do cache/start, anote (contém, nós) → é o **melhor atual**.
> 2. Escolha a direção padrão **↓** (baixar o parâmetro → tipicamente sobe contém).
> 3. Dê um passo nessa direção. Compare com o melhor atual:
>    - **Melhorou** → atualize o melhor, continue na mesma direção.
>    - **Não melhorou** (estagnou ou piorou) → **inverta a direção** (↑) a partir do start.
> 4. Na direção invertida, dê um passo. Compare com o melhor:
>    - **Melhorou** → atualize o melhor, continue na direção invertida.
>    - **Não melhorou** → esta rampa esgotou. Guarde o melhor e passe p/ a rampa seguinte.
> 5. Pare também ao atingir **piso** ou **teto** da rampa.
>
> **1ª rampa: `--min-dist`** · piso **1 mm** · teto **~10** · direção padrão **↓**
> Alavanca principal. NÃO existe `--max-nodes`: nós emergem do espaçamento. Contra-intuitivo:
> min-dist GRANDE = âncoras esparsas → Béziers longos arqueiam p/ dentro → contém MENOR.
>
> **2ª rampa: `--smooth-mm`** · piso **~2** · teto **~10** · direção padrão **↓**
> Engaja quando min-dist esgotou. Baixar aproxima o piso da peça crua e sobe contém; subir tira
> serrilhado. Abaixo de ~2 reintroduz serrilha.
>
> **3ª rampa: `--pocket-eps`** · piso **0** · teto **0.5** · direção padrão **↓**
> Engaja quando as duas primeiras esgotaram. Efeito pequeno por degrau (~+0.0001–0.0003).
> Degraus típicos: 0.5, 0.3, 0.1, 0.
>
> Se esgotarem **todas** as rampas sem cruzar 0.9999, entregue o melhor resultado obtido e reporte
> explicitamente o que faltou.
>
> **Conheça TODOS os flags:** antes de calibrar, leia o [manual de parâmetros](../../../docs/manual.md)
> (`docs/manual.md`) — detecção (`--shadow`, `--symmetry`), suavização, modos (`--faithful`,
> `--tol-fit`) etc. Depois de bater o gate, **explore os demais** (um por passe) rumo a uma
> "quase default" por peça (ver "Cada passe").

## Invocação

`/ptoo <foto.jpg> --pass N [--debug]`

- `<foto>`: 1º argumento. Se for nome simples, resolva na raiz do repo (`C:\PtoO\<foto>`).
- `--pass N`: máximo de tentativas de calibração (default 3 se omitido). É um **teto rígido**.
- `--debug`: ativa o modo crítico (ver seção própria) **além** de calibrar.

**Sempre** use o Python do venv: `.venv/Scripts/python`. Trabalhe a partir de `C:\PtoO`.

## Antes do laço

1. Leia o [manual de parâmetros](../../../docs/manual.md) (conhecer todos os flags) e a
   [memory.md](memory.md). Params iniciais: pegue `--shadow`/`--smooth-mm` do `## cache último-bom`
   (linha de dimensão parecida) ou do `## start`. **`--min-dist` é a alavanca: comece folgado
   (~4) e BAIXE** — o cache só diz onde a rampa provavelmente vai parar (use-o p/ encurtar a
   busca, não p/ pular direto pro fundo).
2. Defina `name` = nome da foto sem extensão; `out` = `<name>.svg`.
3. **Avalie simetria** já no 1º passe (depois do 1º overview): se a peça tem eixo de espelho
   claro, ligue `--symmetry vertical|horizontal` (eixo do objeto) desde o início — limpa ruído
   dos lados e sobe `contém` (parâmetro importante). Nunca em peça assimétrica (distorce).
4. Tiles vão para o scratchpad: `…/scratchpad/ptoo_tiles/<name>/` (transitório).

## Cada passe (repita até `contém` ≥ 0.9999 OU passes esgotados)

1. **Rode a CLI** (sempre com `--inkscape` e `--debug-dir`, necessários p/ inspeção/diagnóstico):
   ```
   .venv/Scripts/python photo_to_outline.py --in <foto> --out <name>.svg \
       <params-atuais> --inkscape --debug-dir _debug/ptoo_<name>
   ```
   - Se sair `ERRO: retificação pela base ArUco falhou` → **pare imediatamente**, NÃO gaste
     passes; reporte ao usuário que é problema da foto (imprimir base.svg em A4 100%, refotografar
     perto do nadir, marcadores visíveis, dict casando).

2. **Parseie o stdout** (linha compacta de métricas `key valor | …`):
   - `obj W x H`  → objeto medido (mm)
   - `pocket W x H (folga ±x/±y)`  → **clearance** = (±x, ±y)
   - `contém 0.NNNN`  → **contém** (no `--faithful`/contenção a chave é `encaixe`)
   - nº de Béziers no início da linha; `AVISO: pocket não contém 100%` (stderr).

3. **Gere os zooms** e olhe:
   ```
   .venv/Scripts/python .claude/skills/ptoo/scripts/zoom.py \
       --overlay-svg _overlay_<name>.svg --seg-overlay _overlay_<name>.png \
       --out-dir <scratchpad>/ptoo_tiles/<name>
   ```
   Leia o `overview.png` e os `zoom_*.png` (extremidades + curvatura). Cada zoom mostra o
   **contorno emitido (amarelo)** e, ao lado, **o que o tool segmentou**.

4. **Diagnostique** (visual + números) e ajuste UM ou DOIS parâmetros por passe, usando a tabela
   de heurísticas da [memory.md](memory.md). Mapa rápido:
   | sintoma | ação |
   |---|---|
   | **contém < 0.9999** | Rampas adaptativas com **inversão**: 1ª `--min-dist` (piso 1, teto ~10) → 2ª `--smooth-mm` (piso ~2, teto ~10) → 3ª `--pocket-eps` (piso 0, teto 0.5). Em cada rampa: direção padrão ↓ enquanto melhorar; parou → inverte p/ ↑; piorou na invertida → volta ao melhor e próxima rampa |
   | **resultado melhorou** | Continue na mesma direção da rampa atual |
   | **parou de melhorar** | Inverta a direção; se a invertida também piora, rampa esgotou → próxima |
   | clearance grande / pocket frouxo | sintoma de `--min-dist` **alto** → direção ↓ |
   | escadinha/serrilhado no amarelo | direção ↑ em `--smooth-mm` (+1..2) — conflita com contém |
   | ondulações/saliências na borda PRETA (baixo contraste) | `--mask-smooth-mm` (~1.5-2): regulariza a silhueta na fonte SEM mexer no contém (ortogonal ao smooth-mm) |
   | `--mask-smooth-mm` comeu uma saliência convexa real (aba) | + `--mask-smooth-keep-bumps` |
   | segmentado come a peça / borda arredondada some (peça CROMÁTICA) | `--shadow remove` |
   | corpo CINZA-NEUTRO + sombra projetada vaza (balão p/ um lado) | `--shadow texture` (recorta a sombra pela textura); SEM sombra projetada use ↑`--val-frac ~0.68` |
   | peça simétrica e contorno ruidoso/torto | `--symmetry vertical\|horizontal` |
   | bico/canto vivo | ↑`--min-radius` (+0.5) |
   | quero o contorno EXATO (não pocket) | `--faithful` (bbox = objeto, com snap) |
   | vermelho vaza p/ fundo ou peça clara some no branco | limite de segmentação — sem flag que
     resolva; anote p/ `--debug` |

   Consulte o [manual](../../../docs/manual.md) p/ o efeito completo de cada flag. **Depois de
   esgotar uma rampa**, gaste os passes restantes na rampa seguinte ou **explorando os demais
   parâmetros** (um por passe — `--min-radius`, `--shadow`, `--symmetry`), registrando o efeito,
   rumo a uma "quase default" por peça que você grava na memória.

5. **Pontue e guarde o melhor.** Aceitável exige **contém ≥ 0.9999** e nenhum leak/come visível;
   entre aceitáveis, vence o de **MENOS nós (Béziers)** — i.e., o de MAIOR valor nas rampas
   (maior min-dist, ou maior smooth-mm, ou maior pocket-eps) que ainda cruza;
   empate → menor `max(clearance_x, clearance_y)` (clearance levemente negativo é OK — é o
   flush). Guarde o melhor `.svg` e seus params; **descarte** overlays/tiles do passe pior.

6. **Pare** SÓ quando `contém` ≥ **0.9999** (sem leak/come visível) ou quando os passes
   acabarem. NÃO pare antes por achar o resultado "bom o bastante" — esse foi um erro do passado.
   Se esgotar os passes sem chegar a 0.9999, entregue o melhor e diga explicitamente que não
   bateu o alvo (e o que tentar a seguir).

## Último passe — ajuste manual (`--edit`)

Quando o laço convergir (`contém` ≥ 0.9999) **OU** os passes acabarem, faça **uma última** chamada
com `--edit` e os params vencedores:
```
.venv/Scripts/python photo_to_outline.py --in <foto> --out <name>.svg <params-vencedores> --edit --inkscape
```
Abre a GUI (foto retificada + nós da curva como alças; zoom no cursor, pan). O usuário move/inclui/
exclui nós e clica **Re-traçar** (spline Catmull-Rom G1 pelos nós); ao **Finalizar**, o `.svg` final é
**EXATAMENTE a curva que está na tela** (WYSIWYG — nada é recalculado). A janela **bloqueia** até
Finalizar (ou cancelar; cancelar não grava). **Só no ÚLTIMO passe**: a calibração automática já fez
o melhor possível — não faz sentido ajustar à mão enquanto ainda se itera parâmetro. **Nunca**
acrescente `--edit` nos passes de calibração (eles precisam do stdout/overlay p/ diagnóstico).

## Depois do laço

1. Apresente ao usuário: caminho do `<name>.svg`, métricas do melhor passe (objeto, pocket,
   clearance, contém, nº de Béziers) e 1–2 tiles mais ilustrativos. Diga quais params venceram.
2. **Atualize a [memory.md](memory.md)** (mantenha-a < 100 linhas):
   - Acrescente/substitua 1 linha no `## cache último-bom`: `- ~WxH mm | <params> | contém=…
     clearance=+x/+y`. Se passar de 5 linhas, **remova a mais antiga**. Não duplique objeto igual
     (substitua a linha dele).
   - **Recompute o `## start`** (a melhor aposta) a partir do cache atualizado: numéricos
     (`min-dist`, `smooth-mm`) = **mediana** das linhas; categóricos (`shadow`) = o que venceu na
     **maioria** → `SEMPRE`; `symmetry` é por-peça, fica sempre `CONDICIONAL` (nunca no `SEMPRE`).
     Atualize o `n=` da amostra no comentário. O `start` nunca é fixo — ele acompanha o cache.
   - Só toque nas heurísticas se aprendeu algo claramente novo (sem duplicar).

## Modo `--debug` (crítico) — só quando o usuário passar `--debug`

Após o laço (mesmo tendo convergido), produza um pacote de melhorias da CLI — **não altere a CLI**:
1. Liste o **erro residual** que os parâmetros não resolveram (visto nos tiles/métricas): ex. peça
   clara somindo no branco, leak de fundo, protuberância abaixo do limiar de proeminência, etc.
2. Leia as funções-fonte relevantes e referencie `file:line`:
   `normalize_illumination` ([photo_to_outline.py:569](../../../photo_to_outline.py)),
   `segment_tool` (:600, modos `--shadow remove`/`texture`), `symmetrize_mask` (:736),
   `regularize_silhouette` (:773, base do `--mask-smooth-mm`/`--mask-smooth-keep-bumps`),
   `extract_outline` (:799), `enforce_min_radius` (:394), `fit_closed_beziers_anchored` (:1516) e a
   lógica de protuberância (`PROTRUSION_DEV_MM`, :129).
3. Entregue três coisas:
   - **(a)** diagnóstico em prosa, citando `file:line`;
   - **(b)** um **patch/diff proposto** (NÃO aplicado) com as mudanças sugeridas;
   - **(c)** um **plano da próxima versão decimal** gravado em `docs/melhorias/v<next>.md`.
4. **Versão**: leia de um `VERSION` na raiz se existir; senão infira do último `v0.x` no
   `git log --oneline` (hoje = `0.1`). Incremente **só a parte decimal** (0.1 → 0.2); a parte
   inteira é do usuário, nunca a toque. O arquivo do plano usa esse `v<next>` (ex.: `v0.2.md`).

## Notas

- A suíte deve continuar verde; o fluxo normal não edita a CLI, e `--debug` só *propõe*. Não rode
  os testes a menos que o usuário peça ou você tenha mexido na CLI.
- Os arquivos `_overlay_*` e `_debug/` são ignorados pelo git (rascunhos). O entregável é o `.svg`.
