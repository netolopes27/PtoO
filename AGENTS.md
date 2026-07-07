# AGENTS.md

**Guia ÚNICO para agentes de código** (Claude Code, Gemini CLI, ZCode, …) neste repositório.
[CLAUDE.md](CLAUDE.md) e [GEMINI.md](GEMINI.md) são stubs que importam este arquivo e guardam
apenas o que é específico de cada ferramenta — **conteúdo de comportamento entra AQUI** (ou nos
docs autoritativos abaixo), nunca duplicado nos stubs.

## Docs autoritativos (leia antes de tocar em áreas sensíveis)

Cada assunto tem um dono; não duplique conteúdo entre eles:

- [README.md](README.md) — guia de uso dos CLIs (em **inglês**, voltado a repo público).
- [docs/design.md](docs/design.md) — arquitetura, API, pipeline, **constantes-chave**, decisões,
  testes (contagem canônica).
- [docs/manual.md](docs/manual.md) — referência operacional de **cada flag** (o que faz, default,
  quando mexer, interações).
- [docs/historico.md](docs/historico.md) — evolução e roadmap.

## O que é

**PtoO** (Photo to Outline) converte a **foto** de um objeto apoiado numa **base de calibração
impressa** (moldura de marcadores ArUco + miolo branco, `base.svg`) num **SVG em mm** com o
**contorno externo** da peça — corrigido de perspectiva/inclinação pelos marcadores, na **escala
real** e suavizado para impressão 3D. Objetivo final: a **cavidade (pocket) de encaixe** onde a
peça repousa (gridfinity personalizável). **O fluxo termina no SVG**; levar para OpenSCAD é
trabalho de um exportador externo.

## Convenções obrigatórias

- **Idioma:** *código* (identificadores, arquivos) em **inglês**; *documentação* (comentários,
  docs em `docs/`, este arquivo) em **português do Brasil** — exceto o **README, em inglês**.
  Unidades sempre **mm**.
- **TDD-first:** ao mudar comportamento, ajuste o teste **antes**. "Concluído" = suíte verde.
  Parâmetros novos nascem com *default* (os testes chamam sem os args novos).
- **Sem pip global:** `numpy` + `opencv-python` vivem **só** no venv `./.venv/`; o resto é stdlib.
  **Sempre** rode a tool e os testes com o Python do venv.
- **Caminhos fixos:** `photo_to_outline.py`, `calibration_target.py`,
  `make_calibration_target.py`, `outline_editor.py` e `thermpro.jpg` ficam na **raiz**; os testes
  em `tests/`. Não mova — os testes resolvem paths relativos.

## Comandos

```bash
# Setup (uma vez) — requer Python 3.14 (wheel abi3 do opencv cobre 3.14)
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; Linux/Mac: .venv/bin/python

# Suíte completa (deve ficar 100% verde; contagem canônica em docs/design.md §Testes)
.venv/Scripts/python tests/run_image_tests.py

# Um único teste (sempre com o venv)
.venv/Scripts/python -m unittest tests.test_photo_to_outline.TestAnchoredFit -v

# Gerar a base de calibração (imprimir em A4 a 100%, sem "fit to page")
.venv/Scripts/python make_calibration_target.py --out base.svg

# Rodar a tool (comando de referência)
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --min-dist 0.6 --smooth-mm 2 --inkscape --symmetry vertical
```

## Arquitetura e limites de camada

Quatro módulos na raiz (detalhe em [docs/design.md](docs/design.md)):

- **`calibration_target.py`** — layout do alvo, **PURO (sem OpenCV)**, fonte única do layout.
  `homography_correspondences()` é o **contrato consumido** por `photo_to_outline.py`. Mudar o
  layout aqui muda tanto o que se imprime quanto o que o detector assume — mantenha-os casados.
- **`make_calibration_target.py`** — CLI que renderiza o layout num `base.svg` impressível.
- **`photo_to_outline.py`** — a tool: todo o pipeline de visão **e** o CLI. Constantes-chave no
  topo do arquivo (documentadas em [docs/design.md](docs/design.md) §Constantes).
- **`outline_editor.py`** — editor de nós opcional (`--edit`), em **duas camadas**: **núcleo puro**
  (geometria, testável) + **view tkinter** (glue fino, **não** unit-testada — a view não é
  instanciada no runner headless). WYSIWYG: Finalize grava exatamente a curva exibida.

**Pipeline (foto → SVG):** retificar por homografia ArUco (sai a dimensão real) → normalizar luz
+ segmentar → *(opcionais: `--in2` fusão 2-fotos; `--level auto`; `--symmetry`; `--humble`)* →
extrair contorno → suavizar p/ impressão → ajustar Béziers + emitir SVG. **Modo
padrão = POCKET de encaixe** (cavidade que **contém** a peça, ≥ objeto, não busca fidelidade):
a justeza é a alavanca **`--min-dist`** (menor = mais âncoras = mais justo, **sem teto de nós**);
**`--faithful`** = modo fiel (bbox = objeto). Todos os nós são suaves (G1). Estágios completos em
[docs/design.md](docs/design.md) §Pipeline.

## Testes

Suíte `unittest` em `tests/`, descoberta por `tests/run_image_tests.py` (precisa do venv).
Níveis (A–F), contagem canônica e o detalhe de cada classe: [docs/design.md](docs/design.md)
§Testes — não replique a contagem em outro doc (os guias só dizem "verde").

## Saídas e git

Cada execução emite o entregável `<out>.svg` **e** um overlay `_overlay_<out>.png` (contorno em
vermelho sobre a foto retificada) — **olhe o PNG antes de aceitar o SVG**. O prefixo `_` marca
rascunhos ignorados pelo git (`.gitignore`: `_overlay_*`, `_debug/`, `.venv/`, `__pycache__/`).

## Gotchas

- **`--dict`** do `photo_to_outline.py` **tem que casar** com o dicionário usado em
  `make_calibration_target.py` (padrão `DICT_4X4_50`) — senão a homografia falha.
- O console do Windows é cp1252; os scripts **forçam UTF-8** em `sys.stdout/stderr` (setas, `·`,
  acentos). Preserve isso se tocar I/O.
- Limite físico que **nenhuma** base corrige: a altura do objeto gera paralaxe (o topo flutua
  sobre o papel). Só se mitiga fotografando perto do nadir; o tool **mede e avisa** a inclinação.
- **Calibrador `/ptoo`** (`.claude/skills/ptoo/`, `SKILL.md` + `memory.md` + `runs.tsv`):
  workflow iterativo que dirige a CLI rumo a um pocket justo, inspecionando o contorno com zoom.
  **Não altera a CLI** — o `--debug` só *propõe* mudanças (planos em `docs/melhorias/`). A
  memória (`memory.md`) e o log de treino (`runs.tsv`, 1 linha por passe;
  `scripts/derive_start.py` agrega por forma × tamanho) são compartilhados entre as integrações
  Claude e Gemini.
