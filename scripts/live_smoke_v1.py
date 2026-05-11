from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = str(ROOT / "scripts" / "a_share_mcp_server.py")


def request(proc: subprocess.Popen[str], payload: dict[str, Any]) -> dict[str, Any]:
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")  # type: ignore[union-attr]
    proc.stdin.flush()  # type: ignore[union-attr]
    if payload.get("id") is None:
        return {}
    line = proc.stdout.readline()  # type: ignore[union-attr]
    if not line:
        raise RuntimeError("server closed stdout")
    return json.loads(line)


def result_json(resp: dict[str, Any]) -> dict[str, Any]:
    if "error" in resp:
        return {"ok": False, "error": resp["error"]}
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "{}")
    return json.loads(text)


def ok_payload(payload: dict[str, Any]) -> bool:
    return payload.get("ok") is True


def main() -> int:
    tests: list[tuple[str, dict[str, Any]]] = [
        ("batch_get_quotes", {"symbols": ["600519", "603259"], "limit": 2}),
        ("compare_companies", {"symbols": ["600519", "603259"], "metrics": "total_market_cap,pe_ttm", "limit": 2}),
        ("screen_stocks", {"industry": "白酒", "limit": 3}),
        ("get_market_overview", {"limit": 3}),
        ("get_financial_trends", {"symbol": "603259", "limit": 4}),
        ("classify_announcements", {"symbol": "603259", "limit": 5}),
        ("get_cache_status", {}),
    ]
    proc = subprocess.Popen([sys.executable, SERVER], cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        request(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        request(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        results = []
        for idx, (name, args) in enumerate(tests, 2):
            print(f"running {name}...", file=sys.stderr, flush=True)
            start = time.time()
            payload = result_json(request(proc, {"jsonrpc": "2.0", "id": idx, "method": "tools/call", "params": {"name": name, "arguments": args}}))
            results.append({"tool": name, "ok": ok_payload(payload), "elapsed_sec": round(time.time() - start, 2), "summary": {k: payload.get(k) for k in ["ok", "partial", "count", "source", "tool"] if k in payload}})
        failed = [r for r in results if not r["ok"]]
        print(json.dumps({"ok": not failed, "tested": len(results), "failed": failed, "results": results}, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
