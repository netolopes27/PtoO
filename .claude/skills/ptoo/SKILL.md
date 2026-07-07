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

- `<foto>`: 1º argumento. Se for nome simples, resolva na raiz do repo (`<repo>/<foto>`).
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
2. Defina `name` = nome da foto sem extensão; `out` = `<name>.svg`.
3. **Avalie simetria** já no 1º passe (depois do 1º overview): eixo de espelho claro →
   `--symmetry vertical|horizontal` desde o início (limpa ruído, sobe contém). **Nunca** em peça
   assimétrica (distorce).
4. Tiles vão para o scratchpad: `…/scratchpad/ptoo_tiles/<name>/` (transitório).

## Cada passe (repita até o gate cruzar OU os passes esgotarem)

1. **Rode a CLI** (sempre com `--inkscape` e `--debug-dir`, necessários p/ inspeção/diagnóstico):
   ```
   .venv/Scripts/python photo_to_outline.py --in <foto> --out <name>.svg \
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
       --overlay-svg _overlay_<name>.svg --seg-overlay _overlay_<name>.png \
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

5. **Pontue pelo Ranking e guarde o melhor** `.svg` e seus params; **descarte** overlays/tiles do
   passe pior.

6. **Pare** SÓ com o gate cruzado ou os passes esgotados. Se esgotar sem cruzar, entregue o melhor
   e diga explicitamente que não bateu o alvo (e o que tentar a seguir). **Depois de cruzar o
   gate** (ou esgotar as rampas) com passes sobrando, explore os demais flags (**um por passe** —
   `--min-radius`, `--shadow`, `--symmetry`…), registrando o efeito, rumo a uma "quase default"
   por peça que você grava na memória.

## Último passe — ajuste manual (`--edit`)

Quando o laço convergir **OU** os passes acabarem, faça **uma última** chamada com `--edit` e os
params vencedores:
```
.venv/Scripts/python photo_to_outline.py --in <foto> --out <name>.svg <params-vencedores> --edit --inkscape
```
Abre a GUI (foto retificada de fundo + nós da curva como alças). WYSIWYG: ao **Finalize**, o
`.svg` final é **EXATAMENTE a curva na tela** (nada recalculado); a janela **bloqueia** até
Finalize (cancelar não grava). Controles (barra, rótulos em inglês; detalhe no
[manual](../../../docs/manual.md) §`--edit`):
- **Básico** — arrastar = mover · clique na curva = inserir · botão-direito = excluir · roda =
  zoom no cursor · Ctrl+arrasto = pan de vista · shift+clique (2 nós) + **Line** = reta entre eles.
- **Symmetry** (se `--symmetry`) — espelha cada edição no par; eixo pontilhado arrastável,
  **Mirror ◀/▶** reconstrói um lado como espelho do outro (conserta lado inflado por sombra).
- **Size** — cota W×H verde do objeto (bate a largura com o paquímetro).
- **Rotate** / **Pan** — giro (0.1°) e deslocamento lateral (0.1 mm) finos de foto+contorno.
- **Measure** — medição ponto-a-ponto em mm (trava no eixo; Ctrl = ângulo livre); persiste
  em destaque até excluir com botão-direito.

**Só no ÚLTIMO passe**: nunca use `--edit` nos passes de calibração (eles precisam do
stdout/overlay p/ diagnóstico).

## Depois do laço

1. Apresente ao usuário: caminho do `<name>.svg`, métricas do melhor passe (objeto, pocket,
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
4. **Versão**: leia de um `VERSION` na raiz se existir; senão infira do último `v0.x` no
   `git log --oneline`. Incremente **só a parte decimal** (0.10 → 0.11); a parte inteira é do
   usuário, nunca a toque. O arquivo do plano usa esse `v<next>` (ex.: `v0.11.md`).

## Notas

- A suíte deve continuar verde; o fluxo normal não edita a CLI, e `--debug` só *propõe*. Não rode
  os testes a menos que o usuário peça ou você tenha mexido na CLI.
- Os arquivos `_overlay_*` e `_debug/` são ignorados pelo git (rascunhos). O entregável é o `.svg`.
