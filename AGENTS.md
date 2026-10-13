# Agents: start here

- To operate a phone, use the `verdikt-core` MCP server (see `install.md` to add it) and follow `SKILL.md`.
- To audit a finished run: `verdikt-core verify <run-folder>`.
- To test one assertion against a saved UI tree: `verdikt-core check '<check>' --tree screen.json`.
- Library code lives in `src/verdikt_core/`: `checks` (assertion language), `tree` (element model), `targeting`
  (stable taps), `contracts` (goal contracts), `ledger` (the checker), `session` (operator), `server` (MCP), `drivers`.
