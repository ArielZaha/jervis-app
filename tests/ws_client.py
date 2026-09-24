"""A tiny client for Jervis's window connection, used by the end-to-end tests (and handy for poking a running backend).

    python tests/ws_client.py PORT TOKEN "set a timer for 2 minutes" ...
"""
import asyncio
import json
import sys

import websockets


async def converse(port: int, token: str, lines, wait: float = 20.0, origin=None) -> list:
    url = f"ws://127.0.0.1:{port}/?token={token}" if token else f"ws://127.0.0.1:{port}/"
    headers = {"Origin": origin} if origin else None
    received = []
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        for line in lines:
            if isinstance(line, dict):
                await ws.send(json.dumps(line))
            else:
                await ws.send(json.dumps({"type": "text", "text": line}))
            deadline = asyncio.get_running_loop().time() + wait
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                except asyncio.TimeoutError:
                    break
                received.append(message)
                # a reply to a typed line, or the answer to a settings request, ends this step
                if (message.get("sender") in ("ai", "jervis") and not isinstance(line, dict)) or \
                        (isinstance(line, dict) and message.get("type") in ("settings", "settings_saved", "settings_error",
                                                                           "setup")):
                    break
    return received


if __name__ == "__main__":
    port, token, *lines = sys.argv[1:]
    for m in asyncio.run(converse(int(port), token, lines)):
        if m.get("type") not in ("system_stats",):
            print(json.dumps(m)[:300])
