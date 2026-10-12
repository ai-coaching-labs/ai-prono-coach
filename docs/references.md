# Références examinées le 9 octobre 2026

## AI Running Coach — Marco Mornati

- Dépôt : https://github.com/mmornati/ai-running-coach
- Commit examiné : `68439fa417c46d041b13f954d4bcdc81f0aecc7f`
- Retenus : coach coordinateur, agents spécialisés, skills, configuration personnelle,
  workspace Markdown, contrats JSON, installation par assistant et mode démo.

## AI Finance Coach — Marco Mornati

- Dépôt : https://github.com/mmornati/ai-finance-coach
- Commit examiné : `2dfb0bd9555d18fe2c77c0230f5458dca4208b17`
- Retenus : calculs déterministes séparés du LLM, CLI, MCP en lecture seule,
  dashboard local, mémoire privée, réponses fondées sur les métriques calculées.
- Non reproduits : SQLCipher, open banking, authentification, multi-utilisateur et scheduler.

Projet AI Prono Coach indépendant. L'architecture est inspirée des deux projets, les
prompts et le code ont été écrits pour ce domaine. Pas de réutilisation de leurs données.

## Connecteurs

- The Odds API v4 : https://the-odds-api.com/liveapi/guides/v4/
  Endpoint `/v4/sports/{sport}/odds/`, paramètres `markets=h2h`, `oddsFormat=decimal`,
  `dateFormat=iso`, `regions`. Issue nulle fournie comme `Draw`.
- SDK Python MCP officiel : https://github.com/modelcontextprotocol/python-sdk
  `mcp.server.fastmcp.FastMCP`, transport stdio, décorateur `tool()`.
