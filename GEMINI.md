# GEMINI.md

O guia de agentes deste repositório é **único** e vive em [AGENTS.md](AGENTS.md) (importado
abaixo). **Não duplique conteúdo aqui** — comportamento, convenções, comandos e arquitetura são
editados lá (ou nos docs autoritativos que ele lista). Este arquivo guarda só o que é específico
do Gemini CLI.

@AGENTS.md

## Específico do Gemini CLI

- **Comando `/ptoo`** em [`.gemini/commands/ptoo.toml`](.gemini/commands/ptoo.toml) (invocação
  `/ptoo <foto.jpg> --pass N [--debug]`). Ele **reaproveita** o procedimento e a memória da skill
  do Claude em `.claude/skills/ptoo/` (`SKILL.md` + `memory.md`) — sem duplicar a lógica; a
  `memory.md` é compartilhada entre as duas versões.
