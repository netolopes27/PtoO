# CLAUDE.md

Guia para o Claude Code (claude.ai/code) neste repositório.

> **Docs autoritativos** (não duplique conteúdo entre eles): [README.md](README.md) — uso dos
> CLIs (em **inglês**); [docs/design.md](docs/design.md) — arquitetura, API, pipeline,
> constantes, decisões, testes; [docs/manual.md](docs/manual.md) — referência operacional de
> **cada flag** (o que faz, default, quando mexer); [docs/historico.md](docs/historico.md) —
> evolução e roadmap. Consulte-os ao mexer no comportamento.
>
> **Skill `/ptoo`** (`.claude/skills/ptoo/`, doc própria no `SKILL.md`): calibrador iterativo que
> dirige a CLI a partir de uma foto rumo a um pocket justo, inspecionando o contorno com zoom.
> Invocação: `/ptoo <foto.jpg> --pass N [--debug]`. Não altera a CLI (o `--debug` só *propõe*).

## O que é

**PtoO** (Photo to Outline) converte a **foto** de um objeto sobre uma **base de calibração
impressa** (moldura ArUco + miolo branco) num **SVG em mm** com o **contorno externo** da peça
— corrigido de perspectiva pelos marcadores, na **escala real** e suavizado para impressão 3D.
Objetivo final: gerar a **cavidade (pocket) onde a peça encaixa** (gridfinity personalizável).
O fluxo termina no SVG; levar para OpenSCAD é trabalho de um exportador externo.

## Convenções obrigatórias

- **Idioma:** *código* (identificadores, arquivos) em **inglês**; *documentação* (comentários,
  docs em `docs/`, este arquivo) em **português do Brasil** — exceto o **README, em inglês**
  (guia voltado a repo público). Unidades sempre **mm**.
- **TDD-first:** ao mudar comportamento, ajuste o teste **antes**. "Concluído" = suíte verde.
  Parâmetros novos nascem com *default* (os testes chamam sem os args novos).
- **Sem pip global:** `numpy` + `opencv-python` vivem **só** no venv `./.venv/`; o resto é
  stdlib. **Sempre** rode tool e testes com o Python do venv.

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

## Arquitetura

Quatro módulos na raiz (detalhe completo em [docs/design.md](docs/design.md)):

- **`calibration_target.py`** — layout do alvo, **puro (sem OpenCV)**. Posições/IDs dos
  marcadores ArUco e as correspondências nominais em mm (`homography_correspondences`); liga
  *o que se imprime* ao *que o detector assume*.
- **`make_calibration_target.py`** — CLI que renderiza o layout num `base.svg` impressível.
- **`photo_to_outline.py`** — a tool (~2300 linhas): todo o pipeline de visão **e** o CLI.
- **`outline_editor.py`** — editor de nós opcional (`--edit`), em duas camadas: **núcleo puro**
  (geometria, testável) + **view tkinter** (glue, não testada). WYSIWYG: Finalize grava exatamente
  a curva exibida (Catmull-Rom G1 pelos nós). GUI em inglês; comentários em pt-BR como o resto.

**Pipeline (foto → SVG):** retificar por homografia ArUco (sai a dimensão real) →
normalizar luz + segmentar → *(opcional `--in2`: fusão 2-fotos com luz oposta — registro
automático + fusão direcional, p/ sombra dura e metal claro)* → extrair contorno → suavizar
p/ impressão → ajustar Béziers + emitir SVG. **Modo padrão = POCKET de encaixe**: não busca
fidelidade, busca uma cavidade que **contém** a peça e fica justa (menor `--min-dist` = mais
justo, sem teto de nós; `--faithful` = modo fiel, bbox = objeto). Todos os nós são suaves (G1).
Constantes-chave no topo de `photo_to_outline.py`. Ver [docs/design.md](docs/design.md) para
estágios, API e constantes.

## Testes

Suíte `unittest` em `tests/`, descoberta por `run_image_tests.py`. Níveis: **A** unidade pura
(geometria, homografia, Bézier, `TestAnchoredFit`, `TestProtrusionAnchors`); **B** sintético
ArUco + **B2–B5** segmentação/fusão sintéticas (histerese de borda, textura+watershed,
faint-metal, `TestFuseMasks`); **C** ponta-a-ponta direto de `thermpro.jpg`; **E** núcleo puro
do editor (`test_outline_editor.py` — spline pelos nós, ops de edição, transforms; a view tkinter
não é instanciada no runner headless).

> **Caminhos fixos:** os testes resolvem paths relativos — `photo_to_outline.py` e
> `thermpro.jpg` ficam na **raiz**, os testes em `tests/`. Não mova.

## Saídas e git

Cada execução emite o entregável `<out>.svg` **e** um overlay `_overlay_<out>.png` (contorno
em vermelho sobre a foto retificada) — **olhe o PNG antes de aceitar o SVG**. O prefixo `_`
marca rascunhos ignorados pelo git (`.gitignore`: `_overlay_*`, `_debug/`, `.venv/`).
