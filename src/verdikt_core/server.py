"""The verdikt-core MCP server: device tools plus the obligation ledger, with a finish the checker gates.

    verdikt-core serve --ios <udid> | --android <serial> [--run-dir DIR] [--budget 50] [--http PORT]
"""
from __future__ import annotations

import asyncio
from typing import Literal

from mcp.server.mcpserver import Image, MCPServer

from verdikt_core.session import Session

INSTRUCTIONS = """Operate the phone to accomplish the user's goal. Completion is decided by a checker, not by you.
1. Call `screen`, then record every obligation of the goal with `record` (free): DO for each state change,
   KNOW for each fact to report or use, IF for each condition.
2. Act. Every action returns the screen it produced, with a step number.
3. Close each obligation while its proof is on screen: `close(text, value=<exact text on that screen>)`
   (it defaults to the latest step). A claim the cited screen does not show is not accepted.
   Close as absent only after looking everywhere it could be; the checker challenges absence once.
4. Call `finish(answer)`. It is refused while obligations are open or unproven; continue with the
   actions you have left (the budget does not reset). The final answer is completed from proven facts."""


def build(session: Session) -> MCPServer:
    mcp = MCPServer("verdikt-core", instructions=INSTRUCTIONS)

    def reply(text: str, png: bytes | None) -> list:
        return [text, Image(data=png, format='png')] if png else [text]

    async def run(fn, *args, **kwargs) -> list:
        text, png = await asyncio.to_thread(fn, *args, **kwargs)
        return reply(text, png)

    @mcp.tool(structured_output=False)
    async def screen() -> list:
        """Look at the screen (free). Returns `step N`, the UI elements as `[index] Type "label" value=... id=... (x1,y1)-(x2,y2)`, and a screenshot."""
        return await run(session.look)

    @mcp.tool(structured_output=False)
    async def tap(index: int | None = None, x: int | None = None, y: int | None = None) -> list:
        """Tap an element by [index] from the latest screen (re-found on the live screen first), or a point x,y. Returns the new screen."""
        return await run(session.tap, index, x, y)

    @mcp.tool(structured_output=False)
    async def type_text(text: str, index: int | None = None) -> list:
        """Type text; with [index] the field is tapped until it has focus first. '\\n' presses enter. Returns the new screen."""
        return await run(session.type_text, text, index)

    @mcp.tool(structured_output=False)
    async def swipe(direction: Literal['up', 'down', 'left', 'right'], distance: float = 0.5) -> list:
        """Swipe the finger in `direction` (up scrolls content down). Returns the new screen."""
        return await run(session.swipe, direction, distance)

    @mcp.tool(structured_output=False)
    async def press(key: str) -> list:
        """Press a key (Android: back, home, enter, delete, tab, recents; iOS: home, enter). Returns the new screen."""
        return await run(session.press, key)

    @mcp.tool(structured_output=False)
    async def launch(app: str) -> list:
        """Launch an app by package name (Android) or bundle id (iOS). Returns the new screen."""
        return await run(session.launch, app)

    @mcp.tool(structured_output=False)
    async def wait(seconds: float = 2) -> list:
        """Wait up to 10 s, then return the screen."""
        return await run(session.wait, seconds)

    @mcp.tool()
    async def record(kind: Literal['DO', 'KNOW', 'IF'], text: str) -> str:
        """Record an obligation of the goal (free). DO: a state change. KNOW: a fact to report or use. IF: a condition."""
        return session.record(kind, text)

    @mcp.tool()
    async def close(text: str, value: str | None = None, step: int | None = None, absent: bool = False,
                    explanation: str | None = None) -> str:
        """Close an obligation with `value`, text copied exactly from the screen at `step` (default: the latest).
        Or `absent=True` with `explanation` of every place you looked."""
        return await asyncio.to_thread(session.close, text, value, step, absent, explanation)

    @mcp.tool()
    async def finish(answer: str = '', status: Literal['complete', 'infeasible'] = 'complete') -> str:
        """End the session. Refused while obligations are open or unproven (continue, then call it again)."""
        return await asyncio.to_thread(session.finish, answer, status)

    return mcp
