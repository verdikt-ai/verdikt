# Verdikt on AndroidWorld

Runs the Verdikt device operator on the official AndroidWorld suite (116 tasks,
`suite_utils.create_suite(seed=30, n_task_combinations=1)`), graded by the official
`task.is_successful(env)` with the official step budget `int(10 * complexity)`.

- `tools.py` - the device tool layer over the official env: act-then-observe (each action
  returns the settled screen it produced, so one tool call is one benchmark step), index
  targeting pinned to the last observation, element list + numbered screenshot perception,
  clear-then-type text entry, slow no-fling scrolling, answer and finish.
- `server.py` - those tools as an MCP server over HTTP, hosted inside the runner process
  that owns the env and grader (the agent never sees benchmark files or the device DB).
- `prompt.md` - the operator method: goal extraction, verify-before-finish, question
  answering, device facts, app know-how.
- `runner.py` - one worker per emulator; tasks are claimed with an atomic mkdir so
  several workers split one suite and a re-run resumes. Success = reward if the agent
  called `finish` within budget, else 0 (as in `suite_utils._run_task`).
- `summarize.py` - per-attempt table.

```sh
# one AVD (Pixel 6, API 33) set up once with android_world setup_apps, then N read-only instances:
emulator -avd Verdikt_AndroidWorld_Pilot -port 5580 -grpc 8580 -read-only -no-snapshot -no-window -gpu host
GRPC_VERBOSITY=ERROR PYTHONPATH=. <android_world venv>/bin/python -m benchmarks.androidworld.runner \
    --attempt runs/run1 --console-port 5580 --mcp-port 7800
python -m benchmarks.androidworld.summarize runs/run1
```

Agent: Claude Code CLI (`claude -p`, default model opus) with only the `android` MCP tools
(`--tools ""`, `--strict-mcp-config`, no settings, no memory).
