---
name: proofop
description: Operate an Android emulator/device or an iOS simulator to accomplish a goal, where completion is proven by a checker against recorded screens. Use when asked to do something on a phone, test an app flow on a device, or gather facts from apps.
---

# proofop: operate a phone and prove the result

You have the `proofop` MCP tools for one device. A checker, not you, decides when the goal is done.

1. `screen` to look (free). Then `record` every obligation of the goal (free):
   - `DO` for each state change (each message, booking, edit, setting; one per recipient),
   - `KNOW` for each fact to report or to use later,
   - `IF` for each condition in the goal.
2. Act with `tap`, `type_text`, `swipe`, `press`, `launch`, `wait`. Each returns the new screen and its step number.
3. Close each obligation while its proof is on screen: `close(text, value=<text copied exactly from the screen>)`.
   Close one as `absent` only after looking in every place it could be (threads, details, other tabs, other apps).
4. `finish(answer)`. If it is refused, do what the checker lists with the actions you have left, then finish again.

The run folder keeps every screen, its UI tree, the ledger and a `certificate.json`; `proofop verify <run>` re-checks it.
