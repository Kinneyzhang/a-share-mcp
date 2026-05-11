from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
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


def tool_call(proc: subprocess.Popen[bytes], msg_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = call(proc, {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    assert response is not None
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def main() -> int:
    proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        init = call(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init and init["result"]["serverInfo"]["name"] == "a-share-mcp", init
        call(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        tools = call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = [t["name"] for t in tools["result"]["tools"]]  # type: ignore[index]
        required = {"search_stock", "get_realtime_quote", "get_daily_history", "get_financial_summary", "get_company_snapshot"}
        assert required.issubset(set(names)), names
        search = tool_call(proc, 3, "search_stock", {"keyword": "贵州茅台", "limit": 3})
        assert search["ok"] is True and search["records"], search
        quote = tool_call(proc, 4, "get_realtime_quote", {"symbol": "600519"})
        assert quote["ok"] is True and quote["symbol"] == "600519", quote
        hist = tool_call(proc, 5, "get_daily_history", {"symbol": "600519", "start_date": "20260501", "limit": 3})
        assert hist["ok"] is True and hist["count"] >= 1, hist
        snapshot = tool_call(proc, 6, "get_company_snapshot", {"symbol": "600519", "history_days": "bad", "announcement_limit": "bad"})
        assert snapshot["ok"] is True and snapshot["quote"] and snapshot["sources"], snapshot
        print(json.dumps({"ok": True, "tools": len(names), "search_first": search["records"][0], "quote_name": quote["quote"].get("name"), "history_count": hist["count"], "snapshot_name": snapshot.get("name"), "snapshot_partial": snapshot.get("partial")}, ensure_ascii=False, indent=2))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
