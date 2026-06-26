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
abaixo disso. Entre resultados que batem 0.9999, prefira o de **menos nós** (pocket mais simples);
clearance é só desempate secundário. A folga real vem do `--clearance` aplicado a jusante. Limite
de tentativas = `--pass N`.

> **`--max-nodes`: rampa de baixo p/ cima — comece em 4 e suba.** Procure o **MENOR** número de
> nós que ainda bate `contém ≥ 0.9999`; quanto menos nós, melhor (SVG mais simples). Atenção ao
> mecanismo contra-intuitivo: com **poucos** nós o pocket fica ao mesmo tempo MAIS FROUXO (âncoras
> esparsas → Béziers longos arqueiam p/ dentro nos cantos e cortam a peça) **e** com `contém`
> menor — então poucos nós costuma travar `contém` em ~0.998 e nunca chegar a 0.9999. Suba (4 → 8
> → … dobrando, depois bissecte) até cruzar 0.9999 e pare no primeiro/menor que cruza. NÃO assuma
> que 4 nós "contém mais": meça.
>
> **O lever fino do `contém` é `--smooth-mm`, NÃO `--pocket-eps`.** O piso de contenção é
> construído sobre a silhueta *suavizada*; suavizar demais deixa a peça crua "vazar" por fora.
> Baixar `--smooth-mm` (ex.: 8→2) aproxima o piso da peça crua e empurra `contém` p/ cima — use-o
> p/ raspar os últimos 0.0x quando a rampa de nós encostar em 0.9999. `--pocket-eps` (penetração
> tolerada, default 0.5) quase não mexe no `contém`. Cuidado: `--smooth-mm` ≲1 reintroduz
> serrilhado — fique em ~2.

## Invocação

`/ptoo <foto.jpg> --pass N [--debug]`

- `<foto>`: 1º argumento. Se for nome simples, resolva na raiz do repo (`C:\PtoO\<foto>`).
- `--pass N`: máximo de tentativas de calibração (default 3 se omitido). É um **teto rígido**.
- `--debug`: ativa o modo crítico (ver seção própria) **além** de calibrar.

**Sempre** use o Python do venv: `.venv/Scripts/python`. Trabalhe a partir de `C:\PtoO`.

## Antes do laço

1. Leia [memory.md](memory.md). Params iniciais: pegue `--shadow`/`--min-dist`/`--smooth-mm` do
   `## cache último-bom` (linha de dimensão parecida) ou do `## start`. **`--max-nodes` é exceção:
   sempre comece a rampa baixa (4) e suba** — o cache só diz onde a rampa provavelmente vai parar
   (use-o p/ encurtar a busca, não p/ pular direto pro alto).
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

2. **Parseie o stdout** (números que guiam a decisão):
   - `objeto (medido) = W x H mm`
   - `pocket (SVG, ≥ objeto, folga +x x +y) = W x H mm`  → **clearance** = (+x, +y)
   - `… contém a peça 0.NNNN`  → **contém**
   - contagem de Béziers; `AVISO: … pocket não contém 100% a peça` (stderr).

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
   | **contém < 0.9999** (rampa de nós) | ↑`--max-nodes` (de baixo p/ cima: 4→8→… dobrando, depois bissecte) até cruzar 0.9999; pare no MENOR que cruza. Se a rampa encostar mas não cruzar, raspe com ↓`--smooth-mm` (4→2) |
   | clearance grande / pocket frouxo | sintoma de **poucos** nós (Béziers longos arqueiam p/ dentro): ↑`--max-nodes` aperta os lados E sobe `contém`. `--min-dist 0.5` adensa âncoras. Mas só suba o necessário p/ bater 0.9999 (menos nós é melhor) |
   | escadinha/serrilhado no amarelo | ↑`--smooth-mm` (+1..2) — conflita com o `contém`; ache o equilíbrio |
   | segmentado come a peça / borda arredondada some | `--shadow remove` |
   | peça simétrica e contorno ruidoso/torto | `--symmetry vertical\|horizontal` |
   | bico/canto vivo | ↑`--min-radius` (+0.5) |
   | curva corta/encosta de leve na peça (ajuste fino) | ↓`--pocket-eps` (default 0.5→0); efeito pequeno no `contém`, útil só p/ o último 0.0x |
   | vermelho vaza p/ fundo ou peça clara some no branco | limite de segmentação — sem flag que
     resolva; anote p/ `--debug` |

5. **Pontue e guarde o melhor.** Aceitável exige **contém ≥ 0.9999** e nenhum leak/come visível;
   entre aceitáveis, vence o de **MENOS nós (Béziers)**; empate em nós → menor
   `max(clearance_x, clearance_y)` (clearance levemente negativo é OK — é o flush). Guarde o melhor
   `.svg` e seus params; **descarte** overlays/tiles do passe pior (economia).

6. **Pare** SÓ quando `contém` ≥ **0.9999** (sem leak/come visível) ou quando os passes
   acabarem. NÃO pare antes por achar o resultado "bom o bastante" — esse foi um erro do passado.
   Se esgotar os passes sem chegar a 0.9999, entregue o melhor e diga explicitamente que não
   bateu o alvo (e o que tentar a seguir).

## Depois do laço

1. Apresente ao usuário: caminho do `<name>.svg`, métricas do melhor passe (objeto, pocket,
   clearance, contém, nº de Béziers) e 1–2 tiles mais ilustrativos. Diga quais params venceram.
2. **Atualize a [memory.md](memory.md)** (mantenha-a < 100 linhas):
   - Acrescente/substitua 1 linha no `## cache último-bom`: `- ~WxH mm | <params> | contém=…
     clearance=+x/+y`. Se passar de 5 linhas, **remova a mais antiga**. Não duplique objeto igual
     (substitua a linha dele).
   - **Recompute o `## start`** (a melhor aposta) a partir do cache atualizado: numéricos
     (`max-nodes`, `min-dist`) = **mediana** das linhas; categóricos (`shadow`) = o que venceu na
     **maioria** → `SEMPRE`; `symmetry` é por-peça, fica sempre `CONDICIONAL` (nunca no `SEMPRE`).
     Atualize o `n=` da amostra no comentário. O `start` nunca é fixo — ele acompanha o cache.
   - Só toque nas heurísticas se aprendeu algo claramente novo (sem duplicar).

## Modo `--debug` (crítico) — só quando o usuário passar `--debug`

Após o laço (mesmo tendo convergido), produza um pacote de melhorias da CLI — **não altere a CLI**:
1. Liste o **erro residual** que os parâmetros não resolveram (visto nos tiles/métricas): ex. peça
   clara somindo no branco, leak de fundo, protuberância abaixo do limiar de proeminência, etc.
2. Leia as funções-fonte relevantes e referencie `file:line`:
   `normalize_illumination` ([photo_to_outline.py:548](../../../photo_to_outline.py)),
   `segment_tool` (:578), `symmetrize_mask` (:682), `extract_outline` (:719),
   `enforce_min_radius` (:372), `fit_closed_beziers_anchored` e a lógica de protuberância
   (`PROTRUSION_DEV_MM`).
3. Entregue três coisas:
   - **(a)** diagnóstico em prosa, citando `file:line`;
   - **(b)** um **patch/diff proposto** (NÃO aplicado) com as mudanças sugeridas;
   - **(c)** um **plano da próxima versão decimal** gravado em `docs/melhorias/v<next>.md`.
4. **Versão**: leia de um `VERSION` na raiz se existir; senão infira do último `v0.x` no
   `git log --oneline` (hoje = `0.1`). Incremente **só a parte decimal** (0.1 → 0.2); a parte
   inteira é do usuário, nunca a toque. O arquivo do plano usa esse `v<next>` (ex.: `v0.2.md`).

## Notas

- A suíte (68 testes) deve continuar verde; o fluxo normal não edita a CLI, e `--debug` só
  *propõe*. Não rode os testes a menos que o usuário peça ou você tenha mexido na CLI.
- Os arquivos `_overlay_*` e `_debug/` são ignorados pelo git (rascunhos). O entregável é o `.svg`.
