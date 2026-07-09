---
name: ptoo
description: >-
  Calibra iterativamente a CLI photo_to_outline.py deste repo a partir de uma foto, mirando um
  POCKET de encaixe justo. Use quando o usuário rodar /ptoo <foto.jpg> --pass N [--debug]
  [--describe "texto"], pedir para "gerar/calibrar o contorno/SVG/pocket a partir de uma foto",
  ou ajustar os parâmetros do photo-to-outline. Roda a CLI, inspeciona o contorno com zoom sobre
  a foto, recalibra os parâmetros em até N tentativas e mantém uma memória pequena; --describe
  converte o que o usuário SABE da peça (forma, raio de canto, medidas) em priors de geometria.
---

# Skill /ptoo — calibrador iterativo do photo_to_outline

Automatiza o laço "rodar → olhar o overlay → ajustar flag → repetir" da CLI
`photo_to_outline.py`, mirando um **pocket que contém a peça**.

**Gate rígido:** só pare com `contém` ≥ **0.9999** e nenhum leak/come visível — **nunca** por
"aceitável" abaixo disso (erro do passado). A folga real vem do `--clearance` a jusante. O limite
de tentativas é `--pass N` (teto rígido).

**Ranking ("melhor") — vale em toda comparação entre passes:**
1. cruza o gate (contém ≥ 0.9999) vence quem não cruza;
2. entre os que cruzam: **MENOS nós** (Béziers) — i.e., o **MAIOR** valor de rampa que ainda cruza;
3. entre os que não cruzam: maior `contém`;
4. empate: menor `max(clearance_x, clearance_y)` (levemente negativo é OK — é o flush).

## Rampas adaptativas — definição única (o resto do arquivo e a memory referenciam esta seção)

Três rampas, em ordem. Em cada uma, a partir do valor do cache/start:
1. Rode e anote (contém, nós) → é o **melhor atual**.
2. Direção padrão **↓** (baixar o parâmetro → tipicamente sobe contém). Dê um passo; **melhorou**
   (pelo ranking) → continue na mesma direção; **não melhorou** → inverta p/ **↑** a partir do start.
3. Não melhorou também na invertida → **volte ao melhor** encontrado; rampa esgotou → próxima.
4. Pare também ao atingir piso/teto.

| # | rampa | piso | teto | nota |
|---|---|---|---|---|
| 1ª | `--min-dist` | 1 | ~10 | Alavanca principal. Contra-intuitivo: GRANDE = âncoras esparsas → Béziers longos arqueiam p/ dentro → contém MENOR. v0.10: em peça **RETILÍNEA** comece **no default 10** (retas não arqueiam); em peça orgânica comece no cache/start e desça |
| 2ª | `--smooth-mm` | ~2 | ~10 | Baixar aproxima o piso da peça crua e sobe contém; subir tira serrilhado; abaixo de ~2 reintroduz serrilha |
| 3ª | `--pocket-eps` | 0 | 0.5 | Efeito pequeno (~+0.0001–0.0003/degrau); degraus típicos 0.5, 0.3, 0.1, 0 |

Se esgotarem **todas** sem cruzar o gate, entregue o melhor resultado e reporte explicitamente o
que faltou. NÃO existe `--max-nodes`: a quantidade de nós emerge do espaçamento.

**Conheça TODOS os flags:** antes de calibrar, leia o [manual de parâmetros](../../../docs/manual.md)
(`docs/manual.md`) — a tabela **sintoma → flag** do §6 é a referência de diagnóstico desta skill
(não duplicada aqui), junto com as heurísticas da [memory.md](memory.md).

## Invocação

`/ptoo <foto.jpg> --pass N [--debug] [--describe "texto"]`

- `<foto>`: 1º argumento. Se for nome simples, resolva em **`images/`** (`<repo>/images/<foto>`) —
  é onde as fotos dos itens moram; só `thermpro.jpg` (amostra) fica na raiz, então use o caminho da
  raiz para ela. Se o usuário passar um caminho explícito, respeite-o.
- `--pass N`: máximo de tentativas de calibração (default 3 se omitido).
- `--debug`: ativa o modo crítico (ver seção própria) **além** de calibrar.
- `--describe "texto"`: descrição em **linguagem natural** do que o usuário SABE da peça
  (forma, medidas de paquímetro, material) — ver §Análise da descrição.

**Sempre** use o Python do venv: `.venv/Scripts/python`. Trabalhe a partir da raiz do repo.

## Análise da descrição (`--describe`) — ANTES do laço

O texto do usuário é conhecimento MEDIDO — vale mais que a estatística da segmentação. Analise-o
**antes do 1º passe** e converta em priors estruturados (v0.13 da CLI); diga ao usuário o que
entendeu e quais flags vai usar ("entendi X → vou usar Y"):

| Informação descrita | Ação |
|---|---|
| classe da forma ("é um retângulo…") | `--shape rect`; trate como `shape=retilinea` (start min-dist 10 e coluna do runs.tsv) |
| raio de canto medido ("cantos de 5 mm") | `--corner-radius 5` — a medida do usuário VENCE o raio estatístico |
| dimensões W×H medidas | NÃO viram flag; valide a cada passe: `obj` do stdout vs descrito (desvio > ±0.5 mm → alertar paralaxe/segmentação) |
| simetria declarada / eixo de espelho | `--symmetry vertical\|horizontal` desde o 1º passe |
| features ("gancho", "aba lateral", assimetria) | `--mask-smooth-keep-bumps`; feature assimétrica VETA `--symmetry` |
| material/cor ("cinza-neutro", "metal claro", "creme") | atalhos da memory: `--shadow texture`, ↑`--val-frac`, truque `--in2` |

Com `--shape` ativo, o contorno é **construído** (8 Béziers exatos), não detectado: as rampas de
`--min-dist` **não regem** o resultado — calibre só a **segmentação** (`--shadow`, `--val-frac`,
`--mask-smooth-mm`…) e pule a 1ª rampa. Valide a cada passe a chave `shape … r=… infl +…` das
métricas: `infl` > 0 com raio declarado = raio real menor (desça `--corner-radius` até infl≈0);
`shape FALLBACK` = o modelo não bateu (a CLI avisou por quê) → reporte e siga o caminho genérico
normal. Gate **inalterado**; no ranking, uma **exceção**: o modelo cruza o gate por construção e
tem poucos nós — antes de declará-lo vencedor, compare a **folga** com o melhor passe genérico
(peça com saliência real fora da forma declarada fecha bem mais justa no genérico; ver
memory.md v0.13).

## Antes do laço

1. Leia o [manual](../../../docs/manual.md) e a [memory.md](memory.md). Params iniciais: pegue da
   linha do `## cache último-bom` de dimensão parecida, senão do `## start`. O cache diz onde a
   rampa provavelmente vai fechar — use-o p/ **encurtar** a busca, não p/ pular direto ao fundo.
   Sem linha parecida no cache, rode
   `.venv/Scripts/python .claude/skills/ptoo/scripts/derive_start.py`: ele agrega **todo** o
   histórico ([runs.tsv](runs.tsv)) por forma × tamanho e mostra onde objetos parecidos fecharam.
2. Defina `name` = nome da foto sem extensão; `out` = `images/<name>.svg` (as saídas ficam junto da
   foto em `images/`; a CLI grava `images/_overlay_<name>.*` ao lado). Para a amostra `thermpro`, a
   entrada e a saída ficam na raiz.
3. **Avalie simetria** já no 1º passe (depois do 1º overview): eixo de espelho claro →
   `--symmetry vertical|horizontal` desde o início (limpa ruído, sobe contém). **Nunca** em peça
   assimétrica (distorce).
4. Tiles vão para o scratchpad: `…/scratchpad/ptoo_tiles/<name>/` (transitório).
5. **1º passe SEMPRE com GUI (OBRIGATÓRIO — regra dura, sem exceção):** a PRIMEIRA chamada da CLI
   vai com `--edit`, **inclusive em runs 2-fotos (`--in2`)**. **NUNCA** a substitua por um passe
   "diagnóstico" sem `--edit` (erro do passado): validar registro/segmentação NÃO é motivo p/ pular
   a GUI — o usuário precisa dela p/ **fixar os pontos importantes (pins) já no 1º passe**, o que
   guia a precisão de TODOS os passes seguintes. A GUI serve p/ o usuário fixar a **calibração da
   foto**: **Rotate** (peça torta), **Pan** (viés lateral) **e
   os PONTOS FORTES do contorno** (v0.15) — arrastar um nó p/ a borda verdadeira o marca em
   magenta e vira **pin**: ponto fixo que corrige a segmentação (ex.: sombra) ali — e
   **Finalize**. Tudo fica salvo em `images/<name>.adjust.json` e é **reaplicado
   automaticamente em todos os passes seguintes** (a CLI imprime `ajuste manual aplicado:
   rot … · pan … · N pins`; o status bar da GUI mostra o acumulado). Foto já nivelada, sem viés
   e sem trecho ruim → Finalize direto (nada salvo). Como o fluxo `--edit` imprime chaves
   diferentes (`EDITADO … | contém …`), **rode em seguida a MESMA chamada sem `--edit`** p/
   colher as métricas completas do passe (`pocket`/`folga`) — conta como o mesmo passe. Sidecar
   de sessão anterior já existente → **abra a GUI mesmo assim** (ela mostra o ajuste e os
   pins herdados; confirmar custa um Finalize) — só pule se o usuário disser explicitamente
   que a calibração está OK. **Se o laço fechar já no 1º passe**, o 1º e o último passe
   **coincidem** → a GUI aparece **uma vez só** (o `--edit` do 1º passe JÁ é o final; não abra
   de novo).

## Cada passe (repita até o gate cruzar OU os passes esgotarem)

1. **Rode a CLI** (sempre com `--inkscape` e `--debug-dir`, necessários p/ inspeção/diagnóstico):
   ```
   .venv/Scripts/python photo_to_outline.py --in images/<foto> --out images/<name>.svg \
       <params-atuais> --inkscape --debug-dir _debug/ptoo_<name>
   ```
   Se sair `ERRO: retificação pela base ArUco falhou` → **pare imediatamente**, NÃO gaste passes;
   reporte que é problema da foto (imprimir base.svg em A4 100%, refotografar perto do nadir,
   marcadores visíveis, dict casando).

2. **Parseie o stdout** (linha compacta de métricas `key valor | …`):
   - `obj W x H` → objeto medido (mm)
   - `pocket W x H (folga ±x/±y)` → **clearance** = (±x, ±y)
   - `contém 0.NNNN` → **contém** (no `--faithful` a chave é `encaixe`)
   - nº de Béziers no início da linha; `AVISO: pocket não contém 100%` (stderr).

3. **Gere os zooms** e olhe:
   ```
   .venv/Scripts/python .claude/skills/ptoo/scripts/zoom.py \
       --overlay-svg images/_overlay_<name>.svg --seg-overlay images/_overlay_<name>.png \
       --out-dir <scratchpad>/ptoo_tiles/<name>
   ```
   Leia o `overview.png` e os `zoom_*.png` (extremidades + curvatura). Cada zoom mostra o
   **contorno emitido (amarelo)** e, ao lado, **o que o tool segmentou**.

4. **Diagnostique** (visual + números) e ajuste **UM ou DOIS** parâmetros por passe:
   - `contém` < gate → **§Rampas adaptativas** (acima).
   - Qualquer outro sintoma (serrilhado, sombra, cinza-neutro, saliência comida, peça torta,
     metal sumindo, etc.) → tabela **sintoma → flag** do [manual §6](../../../docs/manual.md) e
     heurísticas da [memory.md](memory.md).
   - Vermelho vazando p/ o fundo ou peça clara sumindo no branco (foto única) = limite de
     segmentação — sem flag que resolva; anote p/ o `--debug`.

5. **Pontue pelo Ranking e guarde o melhor** `.svg` e seus params; **descarte** os tiles de zoom do
   passe pior (transitórios, no scratchpad). Os `images/_overlay_<name>.*` são **sobrescritos** a
   cada passe e **ficam no disco** — **não os apague** (são o registro visual do item; gitignored,
   mas mantidos localmente).

6. **Pare** SÓ com o gate cruzado ou os passes esgotados. Se esgotar sem cruzar, entregue o melhor
   e diga explicitamente que não bateu o alvo (e o que tentar a seguir). **Depois de cruzar o
   gate** (ou esgotar as rampas) com passes sobrando, explore os demais flags (**um por passe** —
   `--min-radius`, `--shadow`, `--symmetry`…), registrando o efeito, rumo a uma "quase default"
   por peça que você grava na memória.

## Último passe — ajuste manual (`--edit`)

Quando o laço convergir **OU** os passes acabarem, faça **uma última** chamada com `--edit` e os
params vencedores:
```
.venv/Scripts/python photo_to_outline.py --in images/<foto> --out images/<name>.svg <params-vencedores> --edit --inkscape
```
Abre a GUI (foto retificada de fundo + nós da curva como alças). WYSIWYG: ao **Finalize**, o
`.svg` final é **EXATAMENTE a curva na tela** (nada recalculado); a janela **bloqueia** até
Finalize (cancelar não grava).

> **O contorno que sai do editor no ÚLTIMO passe é DEFINITIVO — regra dura.** É sempre o que
> permanece como entregável. **NUNCA** pergunte ao usuário se deve mantê-lo (não gaste tokens
> nisso) e **NUNCA** re-rode a MESMA chamada sem `--edit` "p/ recolher métricas pocket/folga":
> sem sidecar isso **recomputa e sobrescreve** a curva finalizada. A chave `EDITADO … | contém …`
> impressa pela própria chamada `--edit` **É** a métrica final — reporte-a e pare. (O "rode em
> seguida sem `--edit`" vale **só no 1º passe**, onde o sidecar de pins/rotate/pan é reaplicado e
> nada se perde.)

Controles completos no [manual](../../../docs/manual.md) §`--edit` (não duplicados aqui). O que o
**calibrador** precisa saber:
- **Pins/segmentos fixos (hierarquia magenta/amarelo, v0.15–v0.18):** nó **reposicionado** (ou
  **duplo-clique** p/ fixar no lugar) fica **magenta = pin**; trecho com as duas pontas pinned =
  **segmento fixo**. Tudo persiste no `images/<name>.adjust.json` e é reaplicado LITERAL em todo
  passe (pins deformam a silhueta; segmentos substituem o arco pela geometria salva). **O
  algoritmo NÃO mexe em setor fixo** → onde há segmento fixo, `--min-dist`/`--smooth-mm`/
  `--pocket-eps` **não mudam nada**: seu campo de trabalho é só o contorno **amarelo**. `AVISO:
  segmento fixo NÃO costurado` (detecção mudou demais entre passes) → **não** compense por
  parâmetro; avise o usuário p/ refazer o trecho no `--edit`.
- **Rotate/Pan** (giro/deslocamento fino de foto+contorno) e **Symmetry/Mirror** (conserta lado
  inflado por sombra) também persistem/agem como o manual descreve; **Size**/**Measure** = cota e
  medição em mm (bater com o paquímetro). Status: `rot … · pan … · pins N · fixed segs M`.

**GUI SEMPRE no 1º passe (Rotate/Pan + pontos fortes/pins, ver §Antes do laço) e SEMPRE no ÚLTIMO
(nós)** — as duas são obrigatórias; se o laço fecha em 1 passe, elas coincidem e a GUI aparece
uma vez só. **Nunca** use `--edit` nos passes intermediários de calibração (eles precisam do
stdout/overlay p/ diagnóstico).

## Depois do laço

1. Apresente ao usuário: caminho do `images/<name>.svg`, métricas do melhor passe (objeto, pocket,
   clearance, contém, nº de Béziers), 1–2 tiles mais ilustrativos e os params vencedores.
2. **Registre no log [runs.tsv](runs.tsv)** (append-only, **sem teto** — é o banco de treino da
   skill): **uma linha por PASSE do laço**, não só o vencedor — a trajetória é o que ensina as
   rampas. Colunas = cabeçalho do próprio arquivo; desconhecido = `-`; `pass` = nº do passe
   (1-based; `0` é reservado a sementes legado); `gate=1` se AQUELE passe cruzou o gate;
   `winner=1` só na linha do melhor passe; `shape` ∈ `retilinea|organica|mista`; `cond` = tags
   curtas separadas por `;` (croma, cinza-neutro, sombra-projetada, 2fotos, clara-papel,
   `describe` quando o usuário descreveu a peça, …); flags fora das colunas vão em `extra_flags`
   (inclui `--shape`/`--corner-radius`); a essência da descrição vai na `note`.
3. **Atualize a [memory.md](memory.md)** (mantenha-a < 100 linhas) — regras de atualização
   (fonte única, a memory só as referencia):
   - **Cache:** acrescente/substitua 1 linha no `## cache último-bom`: `- ~WxH mm | <params> |
     contém=… clearance=… | nota curta`. Máx. 5 linhas (evicta a mais antiga); objeto igual
     substitui a própria linha (não duplica). O histórico completo vive no runs.tsv — o cache é
     só o atalho de partida.
   - **Start (recomputar a cada update):** rode
     `.venv/Scripts/python .claude/skills/ptoo/scripts/derive_start.py` e transcreva a sugestão
     (medianas dos vencedores do runs.tsv, `min-dist` **por forma**, `shadow` por maioria).
     `symmetry` é por-peça → sempre `CONDICIONAL` (nunca no `SEMPRE`). Atualize o `n=`.
   - Só toque nas heurísticas se aprendeu algo claramente novo (sem duplicar o manual §6).

## Modo `--debug` (crítico) — só quando o usuário passar `--debug`

Após o laço (mesmo tendo convergido), produza um pacote de melhorias da CLI — **não altere a CLI**:
1. Liste o **erro residual** que os parâmetros não resolveram (visto nos tiles/métricas).
2. Leia as funções-fonte relevantes e referencie `file:line` (confirme a linha com um grep — o
   arquivo evolui): `normalize_illumination` (~:661), `segment_tool` (~:715, modos `--shadow
   remove`/`texture`), `estimate_level_angle`/`level_rect_and_mask` (~:1100/:1132, `--level`),
   `symmetrize_mask` (~:1163), `regularize_silhouette` (~:1200, base do `--mask-smooth-mm`/
   `--mask-smooth-keep-bumps`), `extract_outline` (~:1244), `enforce_min_radius` (~:481),
   `fit_closed_beziers_anchored` (~:2389) e a lógica de protuberância (`PROTRUSION_DEV_MM`, ~:178).
3. Entregue três coisas:
   - **(a)** diagnóstico em prosa, citando `file:line`;
   - **(b)** um **patch/diff proposto** (NÃO aplicado) com as mudanças sugeridas;
   - **(c)** um **plano da próxima versão decimal** gravado em `docs/melhorias/v<next>.md`.
     `docs/melhorias/` é **staging transitório**: quando a versão é implementada, a essência do
     plano é dobrada em `docs/historico.md` (entrada da versão) + `docs/design.md` e o arquivo do
     plano é **removido** — nada de plano implementado sobrevivendo como doc duplicada.
4. **Versão**: leia de um `VERSION` na raiz se existir; senão infira do último `v0.x` no
   `git log --oneline`. Incremente **só a parte decimal** (0.10 → 0.11); a parte inteira é do
   usuário, nunca a toque. O arquivo do plano usa esse `v<next>` (ex.: `v0.11.md`).

## Notas

- A suíte deve continuar verde; o fluxo normal não edita a CLI, e `--debug` só *propõe*. Não rode
  os testes a menos que o usuário peça ou você tenha mexido na CLI.
- Os arquivos `_overlay_*` e `_debug/` são ignorados pelo git (rascunhos). O entregável versionado
  é o `.svg`; mas os `images/_overlay_<name>.*` devem ser **preservados no disco** (não apagar) como
  registro visual do item — só o `_debug/` e os tiles de zoom são transitórios.
