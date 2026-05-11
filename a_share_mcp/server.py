"""Lightweight stdio MCP server for A-share data.

No MCP SDK is required at runtime.  The server accepts both the current MCP SDK
newline-delimited JSON stdio transport and older Content-Length framed JSON-RPC.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Callable

from . import data

SERVER_NAME = "a-share-mcp"
SERVER_VERSION = "0.7.0"


def _tool_schema() -> list[dict[str, Any]]:
    return [
        {
            "name": "a_share_healthcheck",
            "description": "Check whether A-share data adapters are reachable.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "search_stock",
            "description": "Search A-share securities by Chinese name or code.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Chinese name or code, e.g. 贵州茅台 or 600519"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_stock_profile",
            "description": "Get basic A-share company profile from Eastmoney/AkShare.",
            "inputSchema": {
                "type": "object",
                "properties": {"symbol": {"type": "string", "description": "A-share code, e.g. 600519 or SZ000001"}},
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_realtime_quote",
            "description": "Get current quote snapshot and valuation fields from Eastmoney.",
            "inputSchema": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_daily_history",
            "description": "Get daily A-share OHLCV history from Eastmoney.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYYMMDD or YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYYMMDD or YYYY-MM-DD"},
                    "adjust": {"type": "string", "enum": ["none", "qfq", "hfq"], "default": "qfq"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 60},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_financial_indicators",
            "description": "Get financial indicator table for an A-share company.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "start_year": {"type": "string", "default": "2023"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 40, "default": 12},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_financial_summary",
            "description": "Get an agent-friendly summary of core financial indicators for an A-share company.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "start_year": {"type": "string", "default": "2024"},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_business_composition",
            "description": "Get主营构成/business composition table for an A-share company.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search_announcements",
            "description": "Search CNINFO/Eastmoney A-share announcements for a stock.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "keyword": {"type": "string", "default": ""},
                    "category": {"type": "string", "default": "", "description": "e.g. 年报, 半年报, 一季报, 三季报, 财务报告"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_announcement_detail",
            "description": "Get normalized CNINFO announcement metadata, canonical PDF URL, and optional PDF text preview.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "A-share code. Optional when detail_url contains stockCode."},
                    "announcement_id": {"type": "string", "description": "CNINFO announcementId. Optional when detail_url is provided."},
                    "detail_url": {"type": "string", "description": "CNINFO disclosure detail URL."},
                    "org_id": {"type": "string", "description": "CNINFO orgId, if known."},
                    "announcement_time": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, if known."},
                    "include_text": {"type": "boolean", "default": False},
                    "text_mode": {"type": "string", "enum": ["auto", "embedded", "ocr"], "default": "auto", "description": "auto tries embedded text first, then OCR fallback when quality is poor/empty."},
                    "max_chars": {"type": "integer", "minimum": 200, "maximum": 20000, "default": 4000},
                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_company_snapshot",
            "description": "Build an agent-friendly A-share research pack: quote, profile, price stats, financial summary, business composition, recent announcements.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "history_days": {"type": "integer", "minimum": 5, "maximum": 250, "default": 60},
                    "announcement_limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_research_pack",
            "description": "Build a generic structured A-share data pack with source ledger for company analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "history_days": {"type": "integer", "minimum": 20, "maximum": 500, "default": 120},
                    "announcement_limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    "include_reports": {"type": "boolean", "default": False},
                    "report_limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_industry_peers",
            "description": "Get same-industry A-share peers with valuation and market-cap fields.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_peer_comparison",
            "description": "Compare one A-share company against same-industry peers using simple percentile ranks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_index_snapshot",
            "description": "Get quote snapshot for a mainland China index such as 000001, 399001, 399006, 000300.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "default": "000001"}}, "additionalProperties": False},
        },
        {
            "name": "get_sector_snapshot",
            "description": "Get A-share industry or concept board snapshot list.",
            "inputSchema": {"type": "object", "properties": {"sector_type": {"type": "string", "enum": ["industry", "concept"], "default": "industry"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}}, "additionalProperties": False},
        },
        {
            "name": "get_sector_components",
            "description": "Get component stocks for an A-share industry or concept board.",
            "inputSchema": {"type": "object", "properties": {"sector_name": {"type": "string"}, "sector_type": {"type": "string", "enum": ["industry", "concept"], "default": "industry"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}, "required": ["sector_name"], "additionalProperties": False},
        },
        {
            "name": "get_financial_events_pack",
            "description": "Get dividend, repurchase, shareholder-change, financing, and restricted-release events for a company.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}, "required": ["symbol"], "additionalProperties": False},
        },
        {
            "name": "get_dividend_events",
            "description": "Get dividend/profit-distribution events for a company.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}, "required": ["symbol"], "additionalProperties": False},
        },
        {
            "name": "get_repurchase_events",
            "description": "Get share repurchase events for a company.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}, "required": ["symbol"], "additionalProperties": False},
        },
        {
            "name": "get_shareholder_change_events",
            "description": "Get shareholder increase/decrease or equity-change events.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}, "required": ["symbol"], "additionalProperties": False},
        },
        {
            "name": "get_financing_events",
            "description": "Get financing-related announcements such as placements, rights issues, convertible bonds.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}, "required": ["symbol"], "additionalProperties": False},
        },
        {
            "name": "get_restricted_release_events",
            "description": "Get restricted-share release/unlock events.",
            "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}, "required": ["symbol"], "additionalProperties": False},
        },
        {
            "name": "get_announcement_layout",
            "description": "Extract best-effort page layout blocks/lines from a CNINFO announcement PDF using OCR or embedded text.",
            "inputSchema": {"type": "object", "properties": {"detail_url": {"type": "string"}, "symbol": {"type": "string"}, "announcement_id": {"type": "string"}, "org_id": {"type": "string"}, "announcement_time": {"type": "string"}, "method": {"type": "string", "enum": ["ocr", "embedded"], "default": "ocr"}, "max_pages": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3}}, "additionalProperties": False},
        },
        {
            "name": "search_research_reports",
            "description": "Search public broker research reports from Eastmoney for background reading.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    ]


def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    tools: dict[str, Callable[..., dict[str, Any]]] = {
        "a_share_healthcheck": lambda **_: data.data_healthcheck(),
        "search_stock": data.search_stock,
        "get_stock_profile": data.get_stock_profile,
        "get_realtime_quote": data.get_realtime_quote,
        "get_daily_history": data.get_daily_history,
        "get_financial_indicators": data.get_financial_indicators,
        "get_financial_summary": data.get_financial_summary,
        "get_business_composition": data.get_business_composition,
        "search_announcements": data.search_announcements,
        "get_announcement_detail": data.get_announcement_detail,
        "get_company_snapshot": data.get_company_snapshot,
        "get_research_pack": data.get_research_pack,
        "get_industry_peers": data.get_industry_peers,
        "get_peer_comparison": data.get_peer_comparison,
        "get_index_snapshot": data.get_index_snapshot,
        "get_sector_snapshot": data.get_sector_snapshot,
        "get_sector_components": data.get_sector_components,
        "get_financial_events_pack": data.get_financial_events_pack,
        "get_dividend_events": data.get_dividend_events,
        "get_repurchase_events": data.get_repurchase_events,
        "get_shareholder_change_events": data.get_shareholder_change_events,
        "get_financing_events": data.get_financing_events,
        "get_restricted_release_events": data.get_restricted_release_events,
        "get_announcement_layout": data.get_announcement_layout,
        "search_research_reports": data.search_research_reports,
    }
    if name not in tools:
        raise ValueError(f"unknown tool: {name}")
    return tools[name](**args)


def _content(result: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}


def _read_message() -> tuple[dict[str, Any], str] | None:
    """Read either SDK JSONL stdio or Content-Length framed JSON-RPC.

    The current Python MCP SDK stdio transport uses newline-delimited JSON.
    Some older/lightweight references use LSP-style Content-Length framing.
    Supporting both makes local smoke tests and real MCP clients happy.
    """
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    stripped = first.strip()
    if stripped.startswith(b"{"):
        return json.loads(stripped.decode("utf-8")), "jsonl"

    headers: dict[str, str] = {}
    text = first.decode("ascii", "replace").strip()
    if ":" in text:
        k, v = text.split(":", 1)
        headers[k.lower()] = v.strip()
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("ascii", "replace").strip()
        if ":" in text:
            k, v = text.split(":", 1)
            headers[k.lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8")), "content-length"


def _send(payload: dict[str, Any], mode: str = "jsonl") -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if mode == "content-length":
        sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(raw)
    else:
        sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def _handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    msg_id = msg.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _tool_schema()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = _dispatch(str(name), dict(arguments))
            return {"jsonrpc": "2.0", "id": msg_id, "result": _content(result)}
        except Exception as exc:
            err = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
            if os.getenv("A_SHARE_MCP_DEBUG") == "1":
                err["traceback_tail"] = traceback.format_exc().splitlines()[-5:]
            result = _content(err)
            result["isError"] = True
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    while True:
        incoming = _read_message()
        if incoming is None:
            return 0
        msg, mode = incoming
        response = _handle(msg)
        if response is not None:
            _send(response, mode=mode)


if __name__ == "__main__":
    raise SystemExit(main())
