# Pulse Post server

Stdlib-only Python server for the Pulse Post TikTok integration.

## Run
```
python3 app.py
```
Listens on $PORT (default 8080).

## Environment variables (set in the host dashboard, never in code)
- TIKTOK_CLIENT_KEY — the app client key (sandbox or production)
- TIKTOK_CLIENT_SECRET — the app client secret
- REDIRECT_URI — default https://ejima0922.github.io/pulse-post/callback.html
- ALLOWED_ORIGIN — default https://ejima0922.github.io

## Endpoints
- GET /health
- POST /api/exchange {code}
- GET /api/session
- POST /api/send (video bytes in body; falls back to ./sample.mp4 if present)
- POST /api/status {publish_id}
