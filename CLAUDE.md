# CLAUDE.md

O guia de agentes deste repositório é **único** e vive em [AGENTS.md](AGENTS.md) (importado
abaixo). **Não duplique conteúdo aqui** — comportamento, convenções, comandos e arquitetura são
editados lá (ou nos docs autoritativos que ele lista). Este arquivo guarda só o que é específico
do Claude Code.

@AGENTS.md

## Específico do Claude Code

- **Skill `/ptoo`** (`.claude/skills/ptoo/`, doc própria no `SKILL.md`): calibrador iterativo
  invocado com `/ptoo <foto.jpg> --pass N [--debug] [--describe "texto"]`. Procedimento, memória e gotchas no
  [AGENTS.md](AGENTS.md) §Gotchas e no próprio `SKILL.md`.
