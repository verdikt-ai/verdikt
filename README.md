# Verdikt Core

Proof-carrying operation for device agents.

**Paper:** [Proof-Carrying Operation: Device Agents Whose Completion Is Checked, Not Declared](https://verdikt-ai.github.io/verdikt/pco/)
([PDF](https://verdikt-ai.github.io/verdikt/pco/paper.pdf) · [every run, frame and statistic](https://verdikt-ai.github.io/verdikt/pco/results/)).
On iOSWorld, PCO raises fully passed tasks from 77/133 to 90/133 (McNemar p = 0.007).

A device agent usually decides for itself that a task is done. Verdikt Core moves that decision to a
checker: the agent states what must be true, cites the recorded screen that shows it, and code
verifies the claim against that screen's UI tree.

- **Check language** (`verdikt_core.ui.checks`): one-line assertions over a UI tree, such as
  `text "Saved" visible`, `count StaticText "Pasta" == 1`, `TextField "Name" value "Ann"`.
- **Contracts** (`verdikt_core.proof.contracts`): a goal contract that gates finishing, expectations on each
  action, and evidence for answers, all decided by the check language.
- **Obligation ledger and checker** (`verdikt_core.proof.ledger`): the goal compiled into DO / KNOW / IF
  obligations; each closed with the claimed value and a cited screen; proven only if that screen
  shows it; absence claims challenged; the answer assembled from proven facts; a certificate per run.
- **Stable targeting** (`verdikt_core.ui.targeting`): the element the agent chose is re-found on the live
  screen before acting, so a layout shift cannot redirect a tap.
- **UI element model** (`verdikt_core.ui.tree`).

## Repository layout

```
src/verdikt_core/
├── ui/         reading screens: element model (tree), check language (checks), stable targeting
├── proof/      the method: obligation ledger and checker (ledger), goal contracts (contracts)
├── runtime/    operating a device: session, evidence store, MCP server, command line
└── drivers/    Android (adb) and iOS (fb-idb)
tests/          mirrors src/ (ui/, proof/, runtime/)
benchmarks/     the AndroidWorld and iOSWorld harnesses, statistics, results site and paper
```

## Use it

```sh
pipx install "verdikt-core[ios]"
claude mcp add phone -- verdikt-core serve --android emulator-5554     # or: --ios <simulator-udid>
```

Then ask your agent to do something on the phone. It records the goal's obligations, acts, closes each one
with evidence, and can only finish once the checker accepts the ledger. Every run leaves a folder with each
screen, its UI tree, the ledger and `certificate.json`; `verdikt-core verify <run>` re-checks it. See `install.md`,
`SKILL.md` and `AGENTS.md`.

Status: pre-release. The AndroidWorld / iOSWorld benchmark runners and the results site will follow.

License: Apache-2.0.
