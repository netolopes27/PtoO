# Manual de parâmetros — `photo_to_outline.py`

> Referência **operacional** de cada flag do CLI: o que faz, default, quando mexer, com que
> outras interage e o efeito em **contém** (cobertura da peça) e **folga** (pocket − objeto).
> Não repete a arquitetura/pipeline — para isso veja [design.md](design.md) (estágios, API,
> constantes) e [historico.md](historico.md) (evolução). O guia de uso em inglês é o
> [README.md](../README.md). Este manual é em pt-BR e serve de base para a skill `/ptoo`.
>
> **Unidades: mm.** O modo **padrão é o POCKET de encaixe** (cavidade que CONTÉM a peça, ≥ objeto).

## Visão de 30 segundos

- A **densidade/justeza do pocket** é controlada por **`--min-dist`** (única alavanca; menor =
  mais âncoras = mais justo). **Não existe mais `--max-nodes`** — a quantidade de nós emerge do
  espaçamento.
- O **lever fino do contém** (raspar os últimos 0.0x) é **`--smooth-mm`**.
- A **detecção/segmentação** se ajusta com **`--shadow`** e **`--symmetry`** (e `--dict` para a
  base).
- A **folga real de impressão** NÃO sai daqui: aplique a jusante (OpenSCAD/`--clearance`). O SVG
  sai no tamanho real (`--clearance 0`).

---

## 1. Detecção e segmentação (o que o tool "enxerga" da peça)

### `--shadow {off,remove}`  · default `off`
Liga a **histerese de borda**: cresce os núcleos preto E colorido pela borda arredondada que vira
para a base (bisel preto no topo, *toe* laranja dessaturado no fundo), **só pelos pixels com
croma**, recuperando a borda real que o corte único comia — e **parando na sombra de contato
cinza** (que fica de fora, sem afrouxar o pocket).
- **Quando usar:** a borda arredondada some / a segmentação "come" a peça; peça com bisel escuro.
- **Sintoma oposto:** com `remove`, se a sombra cinza vazasse, ela é barrada (não vaza).
- **Efeito:** sobe a fidelidade da silhueta → pocket mais correto. Quase sempre `remove` em peças
  reais fotografadas.

### `--symmetry {none,vertical,horizontal,both}`  · default `none`
Impõe a simetria do objeto: **espelha e faz a MÉDIA das duas metades** (duas amostras do mesmo
contorno → menos ruído). `vertical` = eixo vertical (metades esq./dir.), `horizontal` = topo/baixo,
`both` = os dois.
- **Quando usar:** peça com eixo de espelho **claro** e contorno ruidoso/torto. Avaliar logo no 1º
  passe (pelo overview).
- **Cuidado:** **nunca** em peça assimétrica — distorce o contorno.
- **Efeito:** limpa ruído lateral e **sobe o contém**.

### `--dict <nome>`  · default `DICT_4X4_50`
Dicionário ArUco da base impressa; **deve casar** com o `base.svg` gerado.
- **Quando mexer:** só se você regerou a base com outro dicionário. Se não casar, a retificação
  falha (`ERRO: retificação pela base ArUco falhou`) — aí é problema de foto/base, não de pocket.

### `--min-radius <mm>`  · default `1.5`
Raio **mínimo** de canto na suavização (evita bico/cusp de 90°).
- **Quando subir (+0.5):** apareceu bico/canto vivo onde devia ser arredondado.
- **Interação:** muito alto arredonda cantos legítimos.

---

## 2. Densidade e contorno do POCKET

### `--min-dist <mm>`  · default `10.0`  ·  **alavanca principal**
Distância **mínima** entre âncoras do **mesmo quadrante**. Cada quadrante recebe **todas** as
extremidades mais externas que fiquem a ≥ este valor umas das outras — **sem teto de nós**: a
quantidade de Béziers emerge só do espaçamento.
- **MENOR** (ex.: 1 → 0.5) = **mais âncoras = pocket mais justo = contém mais alto**.
- **MAIOR** (ex.: 10 → 20) = menos âncoras = pocket mais folgado.
- **Contra-intuitivo:** `--min-dist` **grande** (poucas âncoras) deixa o pocket **mais folgado E
  com contém MENOR** — âncoras esparsas geram Béziers longas que **arqueiam para dentro** nos
  cantos arredondados, cortando a peça. Para **conter** mais, **diminua** `--min-dist`.
- **Como achar o ponto:** ramp de cima para baixo; pare no **MAIOR** `--min-dist` que ainda cruza
  o alvo de contém (menos nós é melhor).

### `--pocket-eps <mm>`  · default `0.5`
Penetração **tolerada** no modo POCKET: a curva pode tocar/cortar a peça até este valor (em vez de
estufar para fora a span inteira por ruído sub-mm → pocket bem mais justo, ainda contendo ~0.998).
- **Menor (0.5 → 0):** corta MENOS a peça → contém um pouco mais alto, pocket levemente mais
  folgado. Efeito **pequeno** no contém (≈ +0.0001).
- **Quando usar:** ajuste fino do último 0.0x quando a curva encosta/corta de leve. Não é o lever
  principal — para mover o contém de verdade, use `--min-dist`.

### `--simplify <mm>`  · default `2.0`  ·  *(modo FIEL)*
Densidade das âncoras do **fecho convexo** no modo `--faithful` (RDP): **MAIOR** = menos nós (mais
"hull"); **MENOR** = contorno mais justo (mais nós). **Não afeta o pocket** (lá quem manda é
`--min-dist`).

### `--guide <mm>`  · default `0.5`  ·  *(modo `--tol-fit`)*
Orçamento de suavização do **guia de forma** usado só no caminho `--tol-fit`: maior = menos
Béziers, cavidade mais folgada. Sem efeito no pocket padrão nem no `--faithful`.

---

## 3. Suavização e dimensão

### `--smooth-mm <mm>`  · default `8.0`  ·  **lever fino do contém**
Janela do low-pass que remove o serrilhado da silhueta. O piso de contenção é construído sobre a
silhueta **suavizada**:
- **Baixar (8 → 2):** aproxima o piso da peça crua → **empurra o contém para cima**. Use para
  raspar os últimos 0.0x quando a rampa de `--min-dist` encosta mas não cruza.
- **Subir (+1..2):** tira escadinha/serrilhado — **conflita** com o contém (suaviza para dentro).
- **Equilíbrio:** ~2 mm. Abaixo de ~1 mm reintroduz serrilha.

### `--clearance <mm>`  · default `0.0`
Folga **externa** aplicada ao contorno. **Padrão 0 = tamanho REAL** (sem ganho). A folga de
encaixe da impressão é aplicada **depois** (a jusante no OpenSCAD, ou à mão). Mexa só se quiser
embutir folga no próprio SVG.

### `--c-fit <mm>`  · default `0.0`
Folga embutida **no SVG** do caminho por contenção; 0 = traço mínimo encostando na peça. Como
`--clearance`, a folga de impressão é normalmente adicionada a jusante. Raramente mexido.

---

## 4. Modos de ajuste (mutuamente relacionados)

| Flag | Default | Modo | bbox | Quando |
|---|---|---|---|---|
| *(nenhuma)* | — | **POCKET de encaixe** | ≥ objeto (sem snap) | padrão; cavidade que contém a peça |
| `--faithful` | off | **FIEL** | = objeto (snap) | contorno **exato** da peça (fecho convexo + subdivisão por contenção). Substitui o antigo `--max-nodes 0` |
| `--tol-fit` | off | por **tolerância** (Schneider) | = objeto (snap) | ajuste por tolerância `--fit-tol` (mais nós). **Tem precedência sobre `--faithful`** |
| `--polyline` | off | polyline cru (`L`) | = objeto | emite o polígono cru em vez de Béziers (`C`) |

### `--fit-tol <mm>`  · default `0.2`
Tolerância do ajuste por tolerância (só com `--tol-fit`).

> **Precedência:** `--tol-fit` desliga o modo ancorado, então `--faithful` é **ignorado** quando
> `--tol-fit` está presente.

---

## 5. Saída e inspeção (não mudam a geometria)

- **`--in` / `-i` `<foto>`** — entrada (obrigatório).
- **`--out` / `-o` `<arquivo.svg>`** — saída; default `<in sem extensão>.svg`.
- **`--inkscape`** (default off) — gera também o overlay **SVG editável** `_overlay_<nome>.svg`
  (foto retificada embutida + Béziers em camadas, no referencial mm) para ajuste fino no Inkscape.
  O overlay **PNG** de conferência (contorno sobre a foto) sai **sempre**.
- **`--debug-dir <dir>`** — grava os estágios intermediários (retificação, iluminação,
  segmentação) para inspeção.
- **`--name <nome>`** — rótulo do contorno no SVG; default = nome da foto.

---

## 6. Tabela "sintoma → flag"

| Sintoma observado | Ação |
|---|---|
| **contém < alvo** (pocket não cobre 100%) | ↓`--min-dist` (adensa âncoras) — alavanca principal |
| contém encosta no alvo mas não cruza | ↓`--smooth-mm` (8→2) para raspar o último 0.0x; ou ↓`--pocket-eps` |
| pocket **folgado demais** / clearance grande | sintoma de `--min-dist` alto → **baixe** `--min-dist` (Béziers longas arqueiam p/ dentro) |
| escadinha/serrilhado no contorno | ↑`--smooth-mm` (+1..2) — conflita com o contém; ache o equilíbrio (~2) |
| borda arredondada some / segmentação come a peça | `--shadow remove` |
| peça simétrica com contorno ruidoso/torto | `--symmetry vertical\|horizontal` (eixo do objeto) |
| bico/canto vivo onde devia arredondar | ↑`--min-radius` (+0.5) |
| quero o contorno **exato** (não pocket) | `--faithful` |
| vermelho/contorno vaza p/ o fundo, ou peça clara some no branco | limite de segmentação — sem flag resolve; sinalizar p/ melhoria da CLI |
| `ERRO: retificação ... ArUco falhou` | problema de foto/base (imprimir base.svg A4 100%, fotografar perto do nadir, marcadores visíveis, `--dict` casando) |
