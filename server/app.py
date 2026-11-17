#!/usr/bin/env python3
"""Pulse Post sandbox server (stdlib only).

Endpoints:
  GET  /health        -> {"ok": true}
  POST /api/exchange  {code}        -> exchange Login Kit code for a token (stored server-side)
  GET  /api/session                 -> whether a token is stored
  POST /api/send      (video bytes) -> send a video to the connected account's
                                       TikTok inbox (video.upload / FILE_UPLOAD)
  POST /api/post      (video bytes, ?title=) -> publish a video directly to the
                                       connected account (video.publish / FILE_UPLOAD,
                                       privacy fixed to SELF_ONLY in this test build)
  POST /api/status    {publish_id}  -> fetch publish status

Config (env):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET  (sandbox or production credentials)
  REDIRECT_URI   default https://ejima0922.github.io/pulse-post/callback.html
  ALLOWED_ORIGIN default https://ejima0922.github.io
  PORT           default 8080
"""
import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get(
    "REDIRECT_URI", "https://ejima0922.github.io/pulse-post/callback.html")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://ejima0922.github.io")
SAMPLE = Path(__file__).with_name("sample.mp4")

TOKEN = {"access_token": None, "open_id": None, "scope": None}

API = "https://open.tiktokapis.com"


def http_json(method, url, headers=None, body=None, form=None):
    data = None
    hdrs = dict(headers or {})
    if form is not None:
        data = "&".join(f"{k}={urllib.request.quote(str(v), safe='')}"
                        for k, v in form.items()).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True})
        if self.path == "/api/session":
            return self._json(200, {"connected": bool(TOKEN["access_token"]),
                                    "open_id": TOKEN["open_id"],
                                    "scope": TOKEN["scope"],
                                    "configured": bool(CLIENT_KEY and CLIENT_SECRET)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/exchange":
            return self.exchange()
        if path == "/api/send":
            return self.send_video()
        if path == "/api/post":
            return self.post_video()
        if path == "/api/status":
            return self.status()
        return self._json(404, {"error": "not found"})

    def exchange(self):
        if not (CLIENT_KEY and CLIENT_SECRET):
            return self._json(503, {"error": "server credentials not configured"})
        code = (self._body().get("code") or "").strip()
        if not code:
            return self._json(400, {"error": "code is required"})
        status, resp = http_json("POST", f"{API}/v2/oauth/token/", form={
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        })
        if status == 200 and resp.get("access_token"):
            TOKEN["access_token"] = resp["access_token"]
            TOKEN["open_id"] = resp.get("open_id")
            TOKEN["scope"] = resp.get("scope")
            return self._json(200, {"ok": True, "open_id": TOKEN["open_id"],
                                    "scope": TOKEN["scope"]})
        return self._json(502, {"error": "token exchange failed", "detail": resp})

    def send_video(self):
        if not TOKEN["access_token"]:
            return self._json(409, {"error": "not connected: complete TikTok sign-in first"})
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else b""
        if not data and SAMPLE.exists():
            data = SAMPLE.read_bytes()
        if not data:
            return self._json(400, {"error": "no video data: send the video bytes in the request body"})
        if len(data) > 256 * 1024 * 1024:
            return self._json(413, {"error": "video too large"})
        size = len(data)
        chunk = size  # single chunk (the whole file is the final chunk)
        status, resp = http_json(
            "POST", f"{API}/v2/post/publish/inbox/video/init/",
            headers={"Authorization": f"Bearer {TOKEN['access_token']}"},
            body={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                  "chunk_size": chunk, "total_chunk_count": 1}})
        info = resp.get("data") or {}
        if status != 200 or not info.get("upload_url"):
            return self._json(502, {"error": "upload init failed", "detail": resp})
        req = urllib.request.Request(info["upload_url"], data=data, method="PUT")
        req.add_header("Content-Type", "video/mp4")
        req.add_header("Content-Length", str(size))
        req.add_header("Content-Range", f"bytes 0-{size - 1}/{size}")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                up_status = r.status
        except urllib.error.HTTPError as e:
            return self._json(502, {"error": "upload PUT failed", "status": e.code,
                                    "detail": e.read().decode(errors="replace")[:500]})
        if up_status not in (200, 201, 206):
            return self._json(502, {"error": "upload PUT unexpected status",
                                    "status": up_status})
        return self._json(200, {"ok": True, "publish_id": info.get("publish_id")})

    def _read_video(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else b""
        if not data and SAMPLE.exists():
            data = SAMPLE.read_bytes()
        if not data:
            return None, (400, {"error": "no video data: send the video bytes in the request body"})
        if len(data) > 256 * 1024 * 1024:
            return None, (413, {"error": "video too large"})
        return data, None

    def _put_upload(self, upload_url, data):
        size = len(data)
        req = urllib.request.Request(upload_url, data=data, method="PUT")
        req.add_header("Content-Type", "video/mp4")
        req.add_header("Content-Length", str(size))
        req.add_header("Content-Range", f"bytes 0-{size - 1}/{size}")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, None
        except urllib.error.HTTPError as e:
            return None, (502, {"error": "upload PUT failed", "status": e.code,
                                "detail": e.read().decode(errors="replace")[:500]})

    def post_video(self):
        if not TOKEN["access_token"]:
            return self._json(409, {"error": "not connected: complete TikTok sign-in first"})
        from urllib.parse import urlparse, parse_qs, unquote
        qs = parse_qs(urlparse(self.path).query)
        title = unquote(qs.get("title", [""])[0]).strip() or "Pulse Post test"
        data, err = self._read_video()
        if err:
            return self._json(err[0], err[1])
        size = len(data)
        status, resp = http_json(
            "POST", f"{API}/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {TOKEN['access_token']}"},
            body={"post_info": {"title": title,
                                "privacy_level": "SELF_ONLY",
                                "disable_comment": False,
                                "disable_duet": False,
                                "disable_stitch": False},
                  "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                  "chunk_size": size, "total_chunk_count": 1}})
        info = resp.get("data") or {}
        if status != 200 or not info.get("upload_url"):
            return self._json(502, {"error": "post init failed", "detail": resp})
        up_status, perr = self._put_upload(info["upload_url"], data)
        if perr:
            return self._json(perr[0], perr[1])
        if up_status not in (200, 201, 206):
            return self._json(502, {"error": "upload PUT unexpected status",
                                    "status": up_status})
        return self._json(200, {"ok": True, "publish_id": info.get("publish_id")})

    def status(self):
        if not TOKEN["access_token"]:
            return self._json(409, {"error": "not connected"})
        publish_id = (self._body().get("publish_id") or "").strip()
        if not publish_id:
            return self._json(400, {"error": "publish_id is required"})
        status, resp = http_json(
            "POST", f"{API}/v2/post/publish/status/fetch/",
            headers={"Authorization": f"Bearer {TOKEN['access_token']}"},
            body={"publish_id": publish_id})
        return self._json(200 if status == 200 else 502,
                          {"ok": status == 200, "detail": resp})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
