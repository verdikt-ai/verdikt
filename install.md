# Install

Requirements: Python 3.10+. Android: `adb` on PATH and a device or emulator. iOS: macOS, Xcode, a booted simulator,
and `idb_companion` (`brew install facebook/fb/idb-companion`).

```sh
pipx install "proofop[ios]"        # or: uv tool install "proofop[ios]"
```

Add it to Claude Code (one device per server):

```sh
claude mcp add phone -- proofop serve --android emulator-5554
claude mcp add iphone -- proofop serve --ios <simulator-udid>
```

Or run it over HTTP for other MCP clients: `proofop serve --ios <udid> --http 7900` (endpoint `http://127.0.0.1:7900/mcp`).

Options: `--run-dir` (where evidence goes), `--budget` (actions per session, default 50), `--rounds` (how many times
the checker may refuse `finish`, default 2).
