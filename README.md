# proofop

Proof-carrying operation for device agents.

A device agent usually decides for itself that a task is done. proofop moves that decision to a
checker: the agent states what must be true, cites the recorded screen that shows it, and code
verifies the claim against that screen's UI tree.

- **Check language** (`proofop.checks`): one-line assertions over a UI tree, such as
  `text "Saved" visible`, `count StaticText "Pasta" == 1`, `TextField "Name" value "Ann"`.
- **Contracts** (`proofop.contracts`): a goal contract that gates finishing, expectations on each
  action, and evidence for answers, all decided by the check language.
- **Obligation ledger and checker** (`proofop.ledger`): the goal compiled into DO / KNOW / IF
  obligations; each closed with the claimed value and a cited screen; proven only if that screen
  shows it; absence claims challenged; the answer assembled from proven facts; a certificate per run.
- **Stable targeting** (`proofop.targeting`): the element the agent chose is re-found on the live
  screen before acting, so a layout shift cannot redirect a tap.
- **UI element model** (`proofop.tree`).

Status: pre-release. Device adapters, a reference MCP server and the AndroidWorld / iOSWorld
benchmark runners will follow (see the architecture plan).

License: Apache-2.0.
