from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SERVER = str(ROOT / "scripts" / "a_share_mcp_server.py")


def write_jsonl(proc: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    proc.stdin.write(raw)  # type: ignore[union-attr]
    proc.stdin.flush()  # type: ignore[union-attr]


def read_jsonl(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    line = proc.stdout.readline()  # type: ignore[union-attr]
    if not line:
        raise RuntimeError("server closed stdout")
    return json.loads(line.decode("utf-8"))


def request(proc: subprocess.Popen[bytes], payload: dict[str, Any]) -> dict[str, Any] | None:
    write_jsonl(proc, payload)
    if payload.get("id") is None:
        return None
    return read_jsonl(proc)


def main() -> int:
    proc = subprocess.Popen([PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        init = request(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init and init["result"]["serverInfo"]["name"] == "a-share-mcp", init
        request(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        tools = request(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = [t["name"] for t in tools["result"]["tools"]]  # type: ignore[index]
        required = {"search_stock", "get_realtime_quote", "get_financial_summary", "get_company_snapshot", "get_research_pack", "get_announcement_detail", "get_industry_peers", "get_peer_comparison", "get_index_snapshot", "get_sector_snapshot", "get_sector_components", "get_financial_events_pack", "get_dividend_events", "get_repurchase_events", "get_shareholder_change_events", "get_financing_events", "get_restricted_release_events", "get_announcement_layout"}
        assert required.issubset(set(names)), names
        err = request(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "unknown_tool", "arguments": {}}})
        assert err and err["result"].get("isError") is True, err
        assert "traceback_tail" not in err["result"]["content"][0]["text"], err
        print(json.dumps({"ok": True, "tools": len(names), "error_shape": "mcp-result-isError"}, ensure_ascii=False, indent=2))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
