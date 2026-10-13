# Benchmarks

The code behind every number in the paper: the two benchmark harnesses, the statistics, the
results explorer and the paper itself. Results land in `$VERDIKT_BENCH` (default `./bench-results`).

```
benchmarks/
├── androidworld/   harness for the official AndroidWorld suite (116 tasks, official grader)
├── iosworld/       harness for iOSWorld (133 tasks, iOSWorld's own judge) and the PCO checker
├── explorer/       statistics (McNemar, Wilson intervals), and the static results site
└── paper/          the paper (HTML + PDF) and its landing page, built from the statistics
```

## AndroidWorld

Self-contained: the official `android_world` environment plus `verdikt_core`. See
[androidworld/README.md](androidworld/README.md) for emulator setup.

```sh
AW_PY=<android_world venv>/bin/python benchmarks/androidworld/run_suite.sh $VERDIKT_BENCH/androidworld-full/run3-opus
# with goal contracts (paper: Config C)
AW_PY=... benchmarks/androidworld/run_suite.sh $VERDIKT_BENCH/androidworld-full/run9-contracts-seed7 --seed 7 --contracts
python -m benchmarks.androidworld.summarize $VERDIKT_BENCH/androidworld-full/run3-opus
```

## iOSWorld

Clone iOSWorld into `$VERDIKT_BENCH/iosworld` and run its setup. Each task is a cold
`claude -p` session whose only tools are a Verdikt MCP server; `iosworld/pco.py` is the
obligation ledger and checker.

| Paper run | Command |
|---|---|
| Baseline | `python -m benchmarks.iosworld.runner --attempt runs/run1-opus` |
| PCO v1 | `... --attempt runs/run2-pco --pco --prompt prompt-pco-v1.md` |
| PCO v2 | `... --attempt runs/run3-pco-v2 --pco --prompt prompt-pco-v2.md --pco-rounds 2` |
| PCO v2 repeat | `... --attempt runs/run4-pco-v2-repeat --shuffle 0 --pco --prompt prompt-pco-v2.md --pco-rounds 2` |
| Ablation, ledger only | `... --attempt runs/run5-v2-ledger-only --shuffle 0 --pco --prompt prompt-pco-v2.md --pco-rounds 0` |

Grade with iOSWorld's `scripts/judge_trajectories.py` (the paper used Claude Sonnet 4.6 as judge).

**Note on the tool server.** The paper's iOSWorld runs used the Verdikt product's MCP server
(`iosworld/serve_verdikt.py`, which imports `verdikt.server`; set `VERDIKT_SRC` to its source).
The product is not open source. `verdikt_core.runtime` provides the same operator with an open
iOS driver (fb-idb), but the paper's numbers were not produced with it. The method itself (the
prompts, `pco.py`, and the checker in `verdikt_core.proof.ledger`) is all here.

## Statistics, results site and paper

```sh
python -m benchmarks.explorer.stats                         # -> $VERDIKT_BENCH/explorer/stats.json
python -m benchmarks.explorer.export $VERDIKT_BENCH/site/pco/results   # the public results site
python -m benchmarks.paper.audit                            # -> $VERDIKT_BENCH/paper/audit.json (checker audit, sample)
python -m benchmarks.paper.build_paper                      # -> $VERDIKT_BENCH/paper/draft.{html,pdf}
python -m benchmarks.paper.build_site_page                  # -> $VERDIKT_BENCH/site/pco/index.html
```
