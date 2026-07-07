---
description: Calibrador iterativo do photo_to_outline.py — de uma foto sobre a base ArUco rumo a um POCKET de encaixe justo (contém >= 0.9999). Uso: /ptoo <foto.jpg> --pass N [--debug] [--describe "texto"]
---

Você vai executar a skill **/ptoo** deste repositório no Antigravity: o calibrador iterativo da
CLI `photo_to_outline.py` que, a partir de uma foto sobre a base de calibração ArUco, busca um
POCKET de encaixe justo. Critério de aceite (gate RÍGIDO): `contém a peça` >= 0.9999.

## Argumentos desta invocação

Extraia os argumentos do texto que o usuário digitou depois de `/ptoo`. Formato esperado:
`<foto.jpg> --pass N [--debug] [--describe "texto"]`.

- `<foto>`: 1º argumento; se for nome simples, resolva na raiz do repositório.
- `--pass N`: teto rígido de tentativas de calibração (default 3 se omitido).
- `--debug`: ativa o modo crítico (descrito no SKILL.md) ALÉM de calibrar.
- `--describe "texto"`: descrição em linguagem natural do que o usuário SABE da peça (forma,
  medidas, material) — analise-a ANTES do laço e converta em priors, como manda o SKILL.md
  (§Análise da descrição).

Se o usuário não passou nenhuma foto, pergunte qual foto usar antes de começar.

## Instruções autoritativas (siga à risca)

1. **LEIA, nesta ordem, antes de qualquer coisa** (são a fonte única do procedimento — este
   workflow é só o adaptador para o Antigravity):
   - `.claude/skills/ptoo/SKILL.md` — o procedimento completo do laço (rodar → inspecionar o
     overlay com zoom → ajustar UM/DOIS flags → repetir), as rampas adaptativas, o ranking e o
     critério de parada.
   - `.claude/skills/ptoo/memory.md` — memória de calibração (start dinâmico, cache último-bom,
     heurísticas, notas de aceite).
   - `docs/manual.md` — referência operacional de cada flag (a tabela sintoma → flag do §6 é a
     referência de diagnóstico).
2. **EXECUTE o laço você mesmo** com as ferramentas do Antigravity (terminal + leitura/escrita
   de arquivos e visualização de imagens), seguindo o SKILL.md à risca.

## Adaptações para o Antigravity (onde o SKILL.md pressupõe o ambiente do Claude)

- **NÃO existe a "Skill tool" do Claude aqui.** Apenas siga o procedimento do SKILL.md diretamente.
- **Read/Edit/Write:** use as ferramentas equivalentes do Antigravity; rode comandos no terminal.
- **Python:** SEMPRE o do venv — `.venv/Scripts/python` (Windows). Trabalhe a partir da raiz do
  repositório.
- **Tiles de zoom:** o SKILL.md manda gravar num "scratchpad" próprio do Claude. Aqui grave em
  `_debug/ptoo_tiles/<name>/` (ignorado pelo git) e gere os zooms com
  `.venv/Scripts/python .claude/skills/ptoo/scripts/zoom.py --overlay-svg _overlay_<name>.svg
  --seg-overlay _overlay_<name>.png --out-dir _debug/ptoo_tiles/<name>`. Abra e OLHE os PNGs
  (overview + zooms) a cada passe — a inspeção visual é obrigatória, não opcional.
- **Registrar o treino:** ao final do laço, faça o append no `.claude/skills/ptoo/runs.tsv`
  (1 linha por PASSE, colunas = cabeçalho do arquivo) exatamente como manda o SKILL.md.
- **Atualizar a memória:** ao final do laço, edite `.claude/skills/ptoo/memory.md` exatamente
  como o SKILL.md descreve (acrescente/substitua a linha do objeto no cache e RECOMPUTE o
  `start` com `.venv/Scripts/python .claude/skills/ptoo/scripts/derive_start.py`), mantendo o
  arquivo < 100 linhas. É a MESMA memória usada pelas versões Claude e Gemini da skill.
