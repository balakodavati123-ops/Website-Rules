"""Live price relay: Upstox's real-time feed in, one-second server-sent events out.

Holds one connection to Upstox's market-data websocket, keeps the latest price of every instrument it watches, and sends
the dashboard what changed every second over plain HTTPS (Server-Sent Events). Read-only: it uses the same analytics
token as the rest of the desk and never places an order.

Run:  UPSTOX_TOKEN=... python server/stream.py            (port 8787, or PORT)
Open: GET /ticks    event stream, one message a second: {"t": epoch, "p": {"NIFTY 50": [last, change%], ...}}
      GET /snapshot every price now
      GET /health   age of the last tick
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import MarketDataFeedV3_pb2 as pb  # noqa: E402
import upstox as U                 # noqa: E402

TOKEN = os.environ.get("UPSTOX_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", "8787"))
MAX_EQ = int(os.environ.get("MAX_EQ", "1500"))                # equities to watch, most traded first
DATA = os.environ.get("DATA_URL", "https://raw.githubusercontent.com/balakodavati123-ops/Website-Rules/data/")
INDICES = {"NSE_INDEX|Nifty 50": "Nifty 50", "NSE_INDEX|Nifty Bank": "Bank Nifty", "NSE_INDEX|India VIX": "India VIX", "BSE_INDEX|SENSEX": "Sensex"}

names: dict[str, str] = dict(INDICES)      # instrument key -> name shown on the page
ticks: dict[str, list] = {}                # name -> [last, change %]
last_tick = 0.0
dirty: set[str] = set()
subscribed: set[str] = set()


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "desk-stream/1.0"}), timeout=20).read())


def universe() -> list[str]:
    """Indices, MCX futures, and the most traded equities. Quotes once at start to rank them."""
    eq = [x for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"]
    for x in eq:
        names[x["instrument_key"]] = x["trading_symbol"]
    q = U.quotes([x["instrument_key"] for x in eq], TOKEN)
    ranked = sorted(eq, key=lambda x: -((q.get(x["instrument_key"]) or {}).get("last_price") or 0) * ((q.get(x["instrument_key"]) or {}).get("volume") or 0))
    keys = [x["instrument_key"] for x in ranked[:MAX_EQ]]
    import desks as D
    from datetime import datetime
    for c in D.mcx_contracts(U.instruments("MCX"), datetime.now(D.IST).date()):
        names[c["key"]] = c["label"]
        keys.append(c["key"])
    for k, v in q.items():                    # seed prices so the page has numbers before the first live tick
        if v.get("last_price") and v.get("net_change") is not None and k in names:
            p = v["last_price"] - v["net_change"]
            ticks[names[k]] = [v["last_price"], round(v["net_change"] / p * 100, 2) if p else 0]
    return list(INDICES) + keys


def authorize() -> str:
    req = urllib.request.Request("https://api.upstox.com/v3/feed/market-data-feed/authorize", headers={"Accept": "application/json", "User-Agent": "desk-stream/1.0", **({"Authorization": f"Bearer {TOKEN}"} if TOKEN != "proxy-injected" else {})})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())["data"]["authorized_redirect_uri"]


def apply(raw: bytes) -> None:
    global last_tick
    r = pb.FeedResponse()
    r.ParseFromString(raw)
    for k, f in r.feeds.items():
        nm = names.get(k)
        c = f.ltpc if f.HasField("ltpc") else (f.fullFeed.marketFF.ltpc if f.HasField("fullFeed") and f.fullFeed.HasField("marketFF") else f.fullFeed.indexFF.ltpc if f.HasField("fullFeed") else None)
        if nm and c is not None and c.ltp:
            ticks[nm] = [c.ltp, round((c.ltp / c.cp - 1) * 100, 2) if c.cp else 0]
            dirty.add(nm)
            last_tick = time.time()


async def feed(keys: list[str]) -> None:
    import websockets
    backoff = 1
    while True:
        try:
            url = await asyncio.to_thread(authorize)
            async with websockets.connect(url, max_size=None, open_timeout=20) as ws:
                backoff = 1
                for i in range(0, len(keys), 200):
                    await ws.send(json.dumps({"guid": f"g{i}", "method": "sub", "data": {"mode": "ltpc", "instrumentKeys": keys[i:i + 200]}}).encode())
                    subscribed.update(keys[i:i + 200])
                async for m in ws:
                    if isinstance(m, bytes):
                        apply(m)
        except Exception as e:
            print("feed error:", type(e).__name__, str(e)[:120], flush=True)
        await asyncio.sleep(min(30, backoff))
        backoff *= 2


CORS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}


async def ticks_sse(req: web.Request) -> web.StreamResponse:
    res = web.StreamResponse(headers={**CORS, "Content-Type": "text/event-stream", "X-Accel-Buffering": "no"})
    await res.prepare(req)
    await res.write(f"data: {json.dumps({'t': time.time(), 'p': ticks})}\n\n".encode())     # everything once, then only what changed
    try:
        while True:
            await asyncio.sleep(1)
            ch = {n: ticks[n] for n in list(dirty)}
            dirty.difference_update(ch)
            await res.write(f"data: {json.dumps({'t': time.time(), 'p': ch})}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return res


async def snapshot(_): return web.json_response({"t": time.time(), "p": ticks}, headers=CORS)
async def health(_): return web.json_response({"names": len(ticks), "subscribed": len(subscribed), "age_s": round(time.time() - last_tick, 1) if last_tick else None}, headers=CORS)


async def main() -> None:
    keys = await asyncio.to_thread(universe)
    print(f"watching {len(keys)} instruments", flush=True)
    app = web.Application()
    app.add_routes([web.get("/ticks", ticks_sse), web.get("/snapshot", snapshot), web.get("/health", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await feed(keys)


if __name__ == "__main__":
    asyncio.run(main())
