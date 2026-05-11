from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PY = "/home/geekinney/.venv/global/bin/python"
SERVER = str(ROOT / "scripts" / "a_share_mcp_server.py")


def frame(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw


def read_msg(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            raise RuntimeError("server closed stdout")
        if line in (b"\r\n", b"\n"):
            break
        k, v = line.decode("ascii").strip().split(":", 1)
        headers[k.lower()] = v.strip()
    length = int(headers["content-length"])
    body = proc.stdout.read(length)  # type: ignore[union-attr]
    return json.loads(body.decode("utf-8"))


def call(proc: subprocess.Popen[bytes], payload: dict[str, Any]) -> dict[str, Any] | None:
    proc.stdin.write(frame(payload))  # type: ignore[union-attr]
    proc.stdin.flush()  # type: ignore[union-attr]
    if payload.get("method", "").startswith("notifications/"):
        return None
    return read_msg(proc)


def main() -> int:
    proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        init = call(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init and init["result"]["serverInfo"]["name"] == "a-share-mcp", init
        call(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        tools = call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = [t["name"] for t in tools["result"]["tools"]]  # type: ignore[index]
        assert "get_realtime_quote" in names and "get_daily_history" in names, names
        quote = call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_realtime_quote", "arguments": {"symbol": "600519"}}})
        text = quote["result"]["content"][0]["text"]  # type: ignore[index]
        q = json.loads(text)
        assert q["ok"] is True and q["symbol"] == "600519", q
        hist = call(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_daily_history", "arguments": {"symbol": "600519", "start_date": "20260501", "limit": 3}}})
        h = json.loads(hist["result"]["content"][0]["text"])  # type: ignore[index]
        assert h["ok"] is True and h["count"] >= 1, h
        print(json.dumps({"ok": True, "tools": len(names), "quote_name": q["quote"].get("name"), "history_count": h["count"]}, ensure_ascii=False, indent=2))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
