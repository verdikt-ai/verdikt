"""MCP surface for the AndroidWorld agent: the Verdikt device tools, served over HTTP
from inside the runner process that owns the official environment and grader.

With contracts on (`--contracts`), actions take `expect`, `answer` takes `evidence`, and a
free `contract` tool records the goal contract (see contracts.py). With them off, the tool
surface is exactly the one earlier attempts ran with."""

import asyncio
import functools
import inspect
import threading
from typing import Literal

import uvicorn
from mcp.server.mcpserver import Image, MCPServer

from . import tools

EXPECT_DOC = (' expect: optional Verdikt checks that must hold on the screen this action produces '
              '(e.g. ["text \\"Saved\\" visible"]); the result reports ok/MISS for each.')
CONTRACT_ONLY = ('expect', 'evidence')


def _reply(text: str, jpeg: bytes | None) -> list:
    return [text, Image(data=jpeg, format='jpeg')] if jpeg else [text]


async def _act(tool: str, **args) -> list:
    args = {k: v for k, v in args.items() if v is not None}
    text, jpeg = await asyncio.to_thread(tools.act, tool, args)
    return _reply(text, jpeg)


async def screen() -> list:
    """Look at the current screen without acting (free: does not use a step). Returns the
    UI element list ([index] class "text" desc= hint= {flags} @(x1,y1,x2,y2) in device pixels
    1080x2400) and a half-size screenshot with clickable elements boxed and numbered."""
    text, jpeg = await asyncio.to_thread(tools.look)
    return _reply(text, jpeg)


async def tap(index: int | None = None, x: int | None = None, y: int | None = None,
              expect: list[str] | None = None) -> list:
    """Tap an element by its [index] from the latest screen, or device-pixel x,y. Returns the new screen."""
    return await _act('tap', index=index, x=x, y=y, expect=expect)


async def double_tap(index: int | None = None, x: int | None = None, y: int | None = None,
                     expect: list[str] | None = None) -> list:
    """Double-tap an element or point. Returns the new screen."""
    return await _act('double_tap', index=index, x=x, y=y, expect=expect)


async def long_press(index: int | None = None, x: int | None = None, y: int | None = None,
                     duration_ms: int = 1000, expect: list[str] | None = None) -> list:
    """Long-press an element or point (context menus, selection mode, text selection). Returns the new screen."""
    return await _act('long_press', index=index, x=x, y=y, duration_ms=duration_ms, expect=expect)


async def type(text: str, index: int | None = None, x: int | None = None, y: int | None = None,
               clear: bool = True, enter: bool = False, expect: list[str] | None = None) -> list:
    """Type text. With index/x,y the field is tapped first to focus it. clear=True (default)
    selects all existing text in the focused field and deletes it before typing; pass
    clear=False to append at the cursor. '\\n' in text presses Enter (new line). enter=True
    presses Enter after typing (submit/search). Returns the new screen."""
    return await _act('type', text=text, index=index, x=x, y=y, clear=clear, enter=enter, expect=expect)


async def press(key: str, repeat: int = 1, expect: list[str] | None = None) -> list:
    """Press a key: back, home, enter, delete (backspace), forward_delete, tab, space, recents,
    escape, search, move_home, move_end, dpad_up/down/left/right, select_all, copy, paste,
    cut, undo, volume_up/down. repeat presses it several times in one step. Returns the new screen."""
    return await _act('press', key=key, repeat=repeat, expect=expect)


async def scroll(direction: Literal['up', 'down', 'left', 'right'], index: int | None = None,
                 amount: Literal['small', 'half', 'page'] = 'half', expect: list[str] | None = None) -> list:
    """Scroll to reveal content further in `direction` (down = see what is below), within the
    scrollable element [index] if given, else the main screen area. Slow swipe, no fling, so
    pickers and lists move predictably. Returns the new screen."""
    return await _act('scroll', direction=direction, index=index, amount=amount, expect=expect)


async def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400,
                expect: list[str] | None = None) -> list:
    """Raw finger swipe in device pixels (e.g. pull down the notification shade from y=0,
    flick a number picker, dismiss an item). Returns the new screen."""
    return await _act('swipe', x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms, expect=expect)


async def drag(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 2000,
               expect: list[str] | None = None) -> list:
    """Press-and-hold at (x1,y1) then drag to (x2,y2) and release (reorder, move, text-selection handles). Returns the new screen."""
    return await _act('drag', x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms, expect=expect)


async def open_app(name: str, expect: list[str] | None = None) -> list:
    """Launch an app by its name (e.g. "Simple Calendar Pro", "Markor", "Settings", "Contacts",
    "Clock", "Chrome", "Files", "Camera", "Audio Recorder", "Broccoli", "Pro Expense",
    "Tasks", "Retro Music", "Simple Gallery Pro", "Simple Draw Pro", "OsmAnd", "VLC",
    "Joplin", "OpenTracks", "Simple SMS Messenger", "Phone"). Returns the new screen."""
    return await _act('open_app', name=name, expect=expect)


async def wait(seconds: int = 2, expect: list[str] | None = None) -> list:
    """Wait 1-10 seconds for something to load, then return the screen."""
    return await _act('wait', seconds=seconds, expect=expect)


async def answer(text: str, evidence: list[str] | None = None) -> list:
    """Give the user the answer to a question-type goal (uses one step). Put only the answer,
    in the format the question asks for. Call finish afterwards."""
    return await _act('answer', text=text, evidence=evidence)


async def finish(status: Literal['complete', 'infeasible'] = 'complete') -> list:
    """End the episode (uses one step). Call exactly once, when the goal is fully achieved and
    verified on screen (or truly impossible). Nothing runs after this."""
    return await _act('finish', status=status)


async def contract(checks: list[str]) -> list:
    """Record the goal contract (free: does not use a step): Verdikt checks that will hold on
    screen once the goal is done, e.g. ["text \\"Pasta\\" visible", "count StaticText ~\\"Pasta\\" == 1",
    "TextField \\"Title\\" value \\"Ann\\"", "Switch \\"Wi-Fi\\" checked", "text \\"Draft\\" absent"].
    Text patterns: "exact", ~"substring" (case-insensitive), /regex/. finish is refused once
    while the contract fails on the current screen. Calling it again replaces the contract."""
    return [await asyncio.to_thread(tools.set_contract, checks)]


ACTIONS = [tap, double_tap, long_press, type, press, scroll, swipe, drag, open_app, wait]


def _without(fn, names: tuple[str, ...]):
    """`fn` with the contract-only parameters removed from its signature, so a run without
    contracts sees the same tool schema as before."""
    sig = inspect.signature(fn)
    if not any(n in sig.parameters for n in names):
        return fn

    @functools.wraps(fn)
    async def wrapper(**kwargs):
        return await fn(**kwargs)

    wrapper.__signature__ = sig.replace(parameters=[p for p in sig.parameters.values() if p.name not in names])
    wrapper.__annotations__ = {k: v for k, v in fn.__annotations__.items() if k not in names}
    return wrapper


def _with_doc(fn, extra: str):
    @functools.wraps(fn)
    async def wrapper(**kwargs):
        return await fn(**kwargs)

    wrapper.__doc__ = (fn.__doc__ or '') + extra
    return wrapper


def build(contracts: bool = False) -> MCPServer:
    mcp = MCPServer('android')
    register = lambda f: mcp.tool(structured_output=False)(f)  # noqa: E731
    register(screen)
    for fn in ACTIONS:
        register(_with_doc(fn, EXPECT_DOC) if contracts else _without(fn, CONTRACT_ONLY))
    if contracts:
        register(_with_doc(answer, ' evidence: optional Verdikt checks for the facts your answer rests on; '
                                   'each must have held on some screen you saw, else the answer is refused once.'))
        register(finish)
        register(contract)
    else:
        register(_without(answer, CONTRACT_ONLY))
        register(finish)
    return mcp


def serve_in_thread(port: int, contracts: bool = False) -> uvicorn.Server:
    app = build(contracts).streamable_http_app()
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
    srv = uvicorn.Server(config)
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        import time
        time.sleep(0.05)
    return srv
