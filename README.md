# Manual — PtoO (Photo to Outline)

Guia prático da linha de comando. Converte a **foto** de um objeto apoiado na **base de
calibração impressa** num **SVG em milímetros** com o **contorno externo** da peça —
corrigido de perspectiva pelos marcadores ArUco, na **escala real** e suavizado para
impressão 3D.

> Para a visão geral do projeto, pipeline interno e roadmap, veja [PROMPT.md](PROMPT.md).
> Este manual foca em **como usar os dois CLIs**.

---

## 1. Pré-requisitos (uma vez)

Requer **Python 3.14**. As deps de visão (`numpy` + `opencv-python`) vivem **só** num venv
isolado `./.venv/` — nunca instale global.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Windows (PowerShell/Git Bash)
# .venv/bin/python -m pip install -r requirements.txt        # Linux/macOS
```

⚠️ **Sempre** rode a tool e os testes com o Python do venv (`.venv/Scripts/python ...`),
não com o `python` do sistema.

Para conferir que está tudo no lugar:

```bash
.venv/Scripts/python tests/run_image_tests.py     # esperado: 50 testes, OK
```

---

## 2. Fluxo completo em 4 passos

```
[1] gerar base.svg  →  [2] imprimir A4 100%  →  [3] fotografar a peça na base  →  [4] photo_to_outline.py
```

1. **Gere a base de calibração** (`make_calibration_target.py`) — garante que o que você
   imprime é exatamente o que o detector espera.
2. **Imprima `base.svg` em A4 a 100%** (sem "ajustar à página"/"fit to page").
3. **Apoie a peça no centro branco** e fotografe **de cima, perto do nadir** (use o anel-guia
   cinza: ele só fica redondo na tela quando a câmera está perpendicular ao papel).
4. **Rode `photo_to_outline.py`** sobre a foto → sai o `.svg` em mm + overlay de conferência.

---

## 3. `make_calibration_target.py` — gerar a base

```bash
.venv/Scripts/python make_calibration_target.py --out base.svg
```

Defaults: A4 paisagem, margem 10 mm, marcador 16 mm, dicionário `DICT_4X4_50` →
**32 marcadores**, miolo branco **233×146 mm**.

| Flag | Default | O que faz |
|------|---------|-----------|
| `--out` | `tools/base.svg` | caminho do SVG gerado (use `base.svg` na raiz) |
| `--orientation` | `landscape` | `landscape` ou `portrait` |
| `--page-margin` | `10.0` | margem da página até a moldura de marcadores (mm) |
| `--marker-mm` | `16.0` | lado de cada marcador ArUco (mm) |
| `--inner-pad` | `6.0` | folga entre a moldura e o miolo branco (mm) |
| `--dict` | `DICT_4X4_50` | dicionário ArUco — **tem que casar** com o `--dict` do `photo_to_outline.py` |

> Se mudar `--dict` aqui, passe o **mesmo** valor ao rodar `photo_to_outline.py`.

---

## 4. `photo_to_outline.py` — foto → contorno SVG

### Uso mínimo

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg
```

Sem `--out`, o SVG sai com o mesmo nome da foto (`thermpro.jpg` → `thermpro.svg`).

### Uso recomendado (o do exemplo de referência)

```bash
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --symmetry vertical --inkscape
```

Saída esperada para a foto de exemplo **no default (POCKET de encaixe, teto 4)**: objeto
medido **67,88 × 71,38 mm**, pocket (SVG) **73,29 × 74,62 mm** (folga +5,4 × +3,2),
**4 Béziers** (nós suaves), **contém a peça 0,9983**. O pocket de 4 pontos ainda folga um
pouco nas laterais; suba o teto (`--max-nodes 8` → folga ~+1,4 mm; `12`, `16`… mais justo)
para um encaixe mais firme, ou `--max-nodes 0` para o contorno **fiel** (18 Béziers, bbox =
objeto). Ver §4.1.

### Saídas geradas

| Arquivo | Quando | O que é |
|---------|--------|---------|
| `<out>.svg` | sempre | o **contorno em mm** (entregável) |
| `_overlay_<out>.png` | sempre | foto retificada + contorno em vermelho — **confira de relance antes de aceitar o SVG** |
| `_overlay_<out>.svg` | só com `--inkscape` | overlay **editável**: foto embutida (camada travada) + Béziers (camada editável), no referencial mm |

> O prefixo `_` marca os overlays como rascunho (ignorados pelo git). Sempre olhe o
> `_overlay_*.png` primeiro: se a segmentação (vermelho) estiver vazando ou comendo a peça,
> ajuste as flags antes de usar o `.svg`.

### 4.1 O modo POCKET de encaixe (`--max-nodes`)

Por padrão o script **não** gera o contorno mais fiel possível — gera um **pocket de
encaixe**: a cavidade onde a peça vai descansar (ex. um recorte num case impresso em 3D).
A prioridade é dupla: a peça **cabe** (o pocket nunca é menor que ela) e fica **firme**
(justo). Como funciona:

1. **Quadrantes.** Divide a peça em `--max-nodes` setores angulares iguais em torno do
   meio da peça (com `4`, um por quadrante).
2. **Extremidades.** Em cada quadrante ancora as **pontas mais externas** com **nós de
   curva suave**, e traça curvas que **contêm** a peça (toca/corta no máximo ~0,5 mm —
   `POCKET_EPS_MM` — para não inflar por ruído sub-mm).
3. **Progressão 4 → 8 → 12 → 16…** Cada `+4` coloca **mais um ponto por quadrante**,
   deixando o pocket **mais justo**. Sempre múltiplos de 4.
4. **Espaçamento (`--min-dist`, default 10 mm).** Os pontos extras de um **mesmo
   quadrante** ficam a **≥ 10 mm** um do outro — a 1ª âncora é a ponta, a 2ª/3ª caem
   ~10 mm adiante, espalhadas pelas bordas (sem aglomerar na ponta). Se a peça for pequena
   demais para caber a cota com esse espaçamento, saem menos pontos que o teto.
5. **Saliências laterais (automático, teto > 4).** O passo 2 ancora os **cantos** (o que é
   mais externo ao centro), mas um **ressalto no meio de uma aresta** (pega de borracha,
   botão lateral) não é "externo" — sem âncora ali, a curva suave **arredondaria por cima**
   dele. Então, além das âncoras de quadrante, o pocket **força uma âncora em cada saliência
   local**: um pico convexo cuja **proeminência** (altura acima da vizinhança) passe de
   `PROTRUSION_DEV_MM` (0,8 mm) ganha nó próprio. Entram **dentro do mesmo teto** (as vagas
   de quadrante cedem o necessário, sempre mantendo ≥ 4). Curvatura suave/uniforme (um
   círculo) **não** dispara — só o pico se ergue acima do fundo. No teto `4` não age (as 4
   vagas são dos cantos).

| `--max-nodes` | pontos/quadrante | resultado (exemplo thermpro) |
|---|---|---|
| `4` (default) | 1 | contém a peça, ainda **folga** nas laterais (~+5 mm) |
| `8` | 2 | **justo** (folga ~+1,4 mm) |
| `12`, `16`, … | 3, 4, … | cada vez mais firme |
| `0` | — | **modo fiel** (sem teto/quadrantes): contorno justo de verdade, bbox = objeto |

> **Importante:** no modo pocket o SVG fica **próximo do tamanho da peça** (a saída reporta
> a folga, ex. `pocket = 73,29 × 74,62 mm`). A curva pode **tocar/cortar de leve** a peça
> (até `POCKET_EPS_MM`, ~0,5 mm) para não estufar por ruído sub-mm — o encaixe real é
> garantido pela folga de impressão que você aplica depois (ver `--clearance`). Se precisa
> do contorno **exato** da peça (bbox = dimensão medida), use `--max-nodes 0`.

### Flags

**Entrada/saída**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--in` / `-i` | **(obrigatório)** | foto de entrada |
| `--out` / `-o` | `<in>.svg` | SVG de saída (mm) |
| `--name` | nome do arquivo | rótulo usado no SVG/overlay |
| `--dict` | `DICT_4X4_50` | dicionário ArUco da base; **deve casar** com `base.svg` |
| `--debug-dir` | — | grava PNGs intermediários (retificada/máscara) p/ diagnóstico |

**Segmentação (qualidade do recorte)**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--shadow` | `off` | `remove` liga a **histerese de borda**: recupera a borda arredondada que vira p/ a base — o **bisel preto no topo** e o **toe laranja dessaturado no fundo** — crescendo só pelos pixels **com croma** (o plástico) e **parando na sombra de contato cinza** da base (que deixaria o pocket frouxo) |
| `--symmetry` | `none` | `vertical` / `horizontal` / `both`: espelha a máscara e faz a **média das metades** (menos ruído). Use quando o objeto é simétrico |

**Forma do contorno (nós e suavização)**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--smooth-mm` | `8.0` | janela do low-pass (mm) que tira o serrilhado. Maior = mais liso |
| `--simplify` | `2.0` | densidade das âncoras (mm): **maior = menos nós** (mais "hull"); **menor = mais justo** (mais nós) |
| `--max-nodes` | `4` | **teto de curvas do POCKET de encaixe** (Béziers suaves), em passos de 4. Divide a peça em **quadrantes** e ancora a **extremidade** de cada setor; as curvas **contêm** a peça. `4` = 1 ponto/quadrante (folgado); `8`,`12`,`16`… = mais 1/quadrante (mais justo). `0` = modo **fiel** ilimitado (bbox = objeto). Ver §4.1 |
| `--min-dist` | `10` | distância **mínima (mm) entre âncoras do mesmo quadrante** no pocket. Espaça os pontos extras (8, 12…) para não aglomerar nas pontas. Ver §4.1 |
| `--min-radius` | `1.5` | raio mínimo de canto (mm); evita cantos de 90° / bicos |
| `--guide` | (constante) | orçamento de suavização (mm): maior = **menos** Béziers, cavidade mais folgada |

**Folga / dimensão**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--clearance` | `0` | folga externa (mm). **0 = tamanho REAL**; aplique a folga de encaixe a jusante |
| `--c-fit` | `0.0` | folga embutida no SVG (mm); 0 = traço mínimo encostando na peça |

**Formato de saída**

| Flag | Default | O que faz |
|------|---------|-----------|
| `--inkscape` | off | gera também o **overlay SVG editável** `_overlay_<out>.svg` p/ ajuste fino |
| `--polyline` | off | emite polilinha crua (`L`) em vez de curvas de Bézier (`C`) |

**Ajuste avançado de Bézier** (raramente preciso)

| Flag | Default | O que faz |
|------|---------|-----------|
| `--tol-fit` | off | ajusta por **tolerância** (mais nós) em vez do mínimo por contenção |
| `--fit-tol` | (constante) | tolerância (mm) do ajuste — só tem efeito com `--tol-fit` |

---

## 5. Conferindo no Inkscape (ajuste fino)

Com `--inkscape`, abra o `_overlay_<out>.svg`:

1. A foto retificada vem numa **camada travada**; o contorno (Béziers, todos com nós
   suaves G1) numa **camada editável**, já no referencial mm.
2. Ajuste os nós sobre a foto onde a segmentação errou.
3. **Apague a camada da foto** e exporte — o resultado já está na **escala real** (mm).

---

## 6. Receitas rápidas

| Situação | O que fazer |
|----------|-------------|
| Peça com **borda arredondada** (topo preto ou rim colorido) cuja borda some | `--shadow remove` |
| Peça **simétrica** e contorno ruidoso | `--symmetry vertical` (ou `horizontal`/`both`) |
| Contorno **serrilhado** | aumente `--smooth-mm` (ex. `12`) |
| Pocket **folgado demais** (quero mais firme) | suba `--max-nodes`: `8`, `12`, `16`… (mais 1 ponto/quadrante por passo) |
| Quero o **contorno fiel** da peça (bbox = objeto) | `--max-nodes 0` |
| **AVISO** "pocket não contém a peça" | suba `--max-nodes` (raro; só se a estufa não bastou) |
| Quero **diagnosticar** a segmentação | `--debug-dir debug/` e olhe as PNGs |
| Quero **editar à mão** depois | `--inkscape` |

---

## 7. Problemas comuns

- **`ERRO: retificação pela base ArUco falhou`** — a base não foi detectada (poucos
  marcadores). Imprima `base.svg` em A4 a **100%**, apoie a peça no centro branco e
  fotografe mais perto do nadir, com boa luz e sem marcadores cobertos. Confirme que o
  `--dict` casa com o usado em `make_calibration_target.py`.
- **Contorno inflado/deslocado** — paralaxe pela **altura** do objeto (o topo flutua sobre
  o papel). Nenhuma base corrige; a tool só **mede e avisa** a inclinação. Fotografe o mais
  perpendicular possível.
- **Peça clara/fosca some no branco** — o objeto se confunde com o miolo branco. Limitação
  conhecida (ver roadmap no [PROMPT.md](PROMPT.md)); melhore o contraste/iluminação.
- **`imagem não encontrada`** — confira o caminho passado em `--in`.

---

## 8. Ver a ajuda embutida

Cada CLI tem `--help` com os textos atualizados direto do código:

```bash
.venv/Scripts/python photo_to_outline.py --help
.venv/Scripts/python make_calibration_target.py --help
```
