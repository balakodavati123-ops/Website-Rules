# Live price relay

Reads Upstox's real-time feed and sends the dashboard its prices every second over HTTPS (Server-Sent Events).
Read-only: it uses the analytics token and never places an order.

To run it without Docker, first build the message definitions once: `pip install grpcio-tools && cd server && python -m grpc_tools.protoc -I. --python_out=. MarketDataFeedV3.proto`.

Run on any always-on machine:

    docker build -f server/Dockerfile -t desk-stream .
    docker run -d --restart=always -p 8787:8787 -e UPSTOX_TOKEN=... desk-stream

Put it behind HTTPS (Caddy, or a Cloudflare Tunnel), then set `docs/stream.json` to `{"url": "https://your-host"}`.
For a quick check, open the dashboard with `?stream=https://your-host`.

Endpoints: `/ticks` (event stream), `/snapshot`, `/health`.

## Orders (off by default)

`backend/executor.py` mirrors the desks' equity and NIFTY option trades to Upstox. Environment:
`EXEC_MODE=sandbox|live` (default off), `UPSTOX_EXEC_TOKEN`, `EXEC_MAX_ORDER_RS`, `EXEC_MAX_DAY_LOSS_RS`, `EXEC_ALGO_NAME`.
Live also needs `EXEC_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY` and the strategy to be READY FOR REVIEW.
A file named `KILL` in the data folder (or `EXEC_KILL=1`) stops everything. Real orders must come from an IP address registered with Upstox.
