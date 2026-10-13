"""The product MCP server (`verdikt.server`) over streamable HTTP, plus `POST /end`, which
runs the product's own `end_session` on the server's event loop. The runner calls it after
the agent stops, so every task leaves a run.json however the agent ended.

    python -m benchmarks.iosworld.serve_verdikt PORT      (with PYTHONPATH=<product>/src)
"""
import sys

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse

from verdikt import server as product


async def end(_: Request) -> JSONResponse:
    if product._session is None:
        return JSONResponse({'ended': False, 'reason': 'no session'})
    try:
        out = await product.end_session(reason='benchmark task ended (runner)')
    except Exception as exc:  # noqa: BLE001 - report, the runner falls back
        return JSONResponse({'ended': False, 'reason': f'{type(exc).__name__}: {exc}'})
    return JSONResponse({'ended': True, 'result': str(out)[:2000]})


app = product.server.streamable_http_app()
app.add_route('/end', end, methods=['POST'])

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
