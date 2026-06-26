# GEMINI.md

Guia para o Gemini CLI neste repositório (paralelo ao [CLAUDE.md](CLAUDE.md)). Ambos apontam para
os mesmos **docs autoritativos** — não duplique comportamento entre eles; ao mexer no
comportamento, consulte e atualize os docs, não estes guias.

## Docs autoritativos
- [README.md](README.md) — uso dos CLIs (em **inglês**).
- [docs/design.md](docs/design.md) — arquitetura, API, pipeline, constantes, decisões, testes.
- [docs/manual.md](docs/manual.md) — referência operacional de **cada flag** (o que faz, default,
  quando mexer, interações).
- [docs/historico.md](docs/historico.md) — evolução e roadmap.

## O que é
**PtoO** (Photo to Outline) converte a **foto** de um objeto sobre uma **base de calibração
impressa** (moldura ArUco + miolo branco) num **SVG em mm** com o **contorno externo** da peça —
corrigido de perspectiva pelos marcadores, na **escala real** e suavizado para impressão 3D.
Objetivo final: gerar a **cavidade (pocket) de encaixe**. O fluxo termina no SVG.

## Convenções obrigatórias
- **Idioma:** *código* (identificadores, arquivos) em **inglês**; *documentação* (comentários,
  docs em `docs/`, este arquivo) em **português do Brasil** — exceto o **README, em inglês**.
  Unidades sempre **mm**.
- **TDD-first:** ao mudar comportamento, ajuste o teste **antes**. "Concluído" = suíte verde.
  Parâmetros novos nascem com *default* (os testes chamam sem os args novos).
- **Sem pip global:** `numpy` + `opencv-python` vivem **só** no venv `./.venv/`; o resto é stdlib.
  **Sempre** rode a tool e os testes com o Python do venv.

## Comandos
```bash
# Setup (uma vez) — requer Python 3.14
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; Linux/Mac: .venv/bin/python

# Suíte completa (esperado: 68 testes, OK)
.venv/Scripts/python tests/run_image_tests.py

# Gerar a base de calibração (imprimir em A4 a 100%, sem "fit to page")
.venv/Scripts/python make_calibration_target.py --out base.svg

# Rodar a tool (comando de referência)
.venv/Scripts/python photo_to_outline.py --in thermpro.jpg --out thermpro.svg \
    --shadow remove --min-dist 0.6 --smooth-mm 2 --inkscape --symmetry vertical
```

> Nota: `requirements.txt` menciona caminhos `tools/` de uma estrutura antiga — **ignore**; hoje
> os arquivos ficam na **raiz**.

## Arquitetura (resumo; detalhe em design.md)
Três módulos na raiz: `calibration_target.py` (layout do alvo, **puro, sem OpenCV**),
`make_calibration_target.py` (renderiza o `base.svg`) e `photo_to_outline.py` (todo o pipeline de
visão **e** o CLI). **Pipeline (foto → SVG):** retificar por homografia ArUco (sai a dimensão
real) → normalizar luz + segmentar → extrair contorno → suavizar p/ impressão → ajustar Béziers +
emitir SVG. **Modo padrão = POCKET de encaixe** (contém a peça, ≥ objeto): a densidade do contorno
é a alavanca **`--min-dist`** (menor = mais justo, **sem teto de nós**); **`--faithful`** = modo
fiel (bbox = objeto, com snap). Todos os nós são suaves (G1).

## Comando `/ptoo`
O calibrador iterativo está em [`.gemini/commands/ptoo.toml`](.gemini/commands/ptoo.toml)
(invocação `/ptoo <foto.jpg> --pass N [--debug]`). Ele **reaproveita** o procedimento e a memória
da skill do Claude em `.claude/skills/ptoo/` (`SKILL.md` + `memory.md`) e a referência de
`docs/manual.md` — sem duplicar a lógica. A `memory.md` é compartilhada entre as duas versões.

## Saídas e git
Cada execução emite o entregável `<out>.svg` **e** um overlay `_overlay_<out>.png` (contorno em
vermelho sobre a foto retificada) — **olhe o PNG antes de aceitar o SVG**. O prefixo `_`, mais
`_debug/` e `.venv/`, são ignorados pelo git.
