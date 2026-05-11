# A Share MCP

[English](README.md) | [简体中文](README.zh-CN.md)

Source-labeled, agent-friendly Chinese A-share data tools exposed as a local stdio MCP server.

A Share MCP is designed for data retrieval and structured research inputs rather than trading automation. It helps AI agents retrieve A-share quotes, price history, financial indicators, business composition, announcements, and compact company data packs with explicit data-source metadata.

> For research and education only. This project does not provide investment advice, trading signals, brokerage integration, or buy/sell recommendations.

## Why this project

There are already broad financial-data MCP servers. This project intentionally stays lightweight and research-oriented:

- **No token required for the MVP** — uses public Eastmoney endpoints and AkShare wrappers.
- **Source-labeled outputs** — every tool returns `source` metadata for downstream audit and citation.
- **Agent-friendly summaries** — `get_financial_summary` and `get_company_snapshot` reduce noisy raw tables into useful research payloads.
- **Local-first stdio MCP** — easy to run in Claude Desktop, Hermes, Cursor, or any MCP client.
- **Conservative by design** — public data can be delayed or incomplete; important facts should be verified against official filings.

## Tools

- `a_share_healthcheck` — Check AkShare / Eastmoney reachability.
- `search_stock` — Search A-share securities by Chinese name or code.
- `get_stock_profile` — Basic company profile.
- `get_realtime_quote` — Quote snapshot, valuation fields, market cap, industry.
- `get_daily_history` — Daily OHLCV history with `none/qfq/hfq` adjustment options.
- `get_financial_indicators` — Raw financial indicator table.
- `get_financial_summary` — Compact core financial metrics for agents.
- `get_business_composition` — Business / revenue composition table.
- `search_announcements` — CNINFO / Eastmoney announcement search with normalized IDs, detail URLs, and PDF URLs.
- `get_announcement_detail` — Normalize a CNINFO announcement detail link and optionally extract a bounded PDF text preview.
- `search_research_reports` — Public broker research search for background reading.
- `get_company_snapshot` — One-call research pack: quote, profile, price stats, financial summary, business composition, and recent announcements.
- `get_research_pack` — Structured company data pack with price records, financials, business composition, announcements, optional broker research, and a source ledger.

## Install

```bash
git clone https://github.com/Kinneyzhang/a-share-mcp.git
cd a-share-mcp
python -m pip install -e .
```

Run the MCP server:

```bash
a-share-mcp
```

Or run from source:

```bash
python scripts/a_share_mcp_server.py
```

## MCP client configuration

Use an absolute path for `args` when configuring desktop/agent clients.

```yaml
mcp_servers:
  a_share:
    command: "python"
    args: ["/ABSOLUTE/PATH/TO/a-share-mcp/scripts/a_share_mcp_server.py"]
    timeout: 180
    connect_timeout: 60
```

If installed as a console script:

```yaml
mcp_servers:
  a_share:
    command: "a-share-mcp"
    args: []
    timeout: 180
    connect_timeout: 60
```

Tool names are usually prefixed by your client, e.g. `mcp_a_share_get_company_snapshot`.

## Smoke test

Deterministic protocol smoke test, suitable for CI:

```bash
python -m py_compile a_share_mcp/*.py scripts/*.py
python scripts/protocol_smoke.py
```

Optional live-data smoke test, useful before local releases:

```bash
python scripts/smoke_mcp.py
```

Live smoke output includes:

```json
{
  "ok": true,
  "tools": 13,
  "quote_name": "贵州茅台"
}
```

## Examples

Search by Chinese name:

```json
{
  "tool": "search_stock",
  "arguments": {"keyword": "药明康德", "limit": 5}
}
```

Build a company research pack:

```json
{
  "tool": "get_company_snapshot",
  "arguments": {"symbol": "603259", "history_days": 60, "announcement_limit": 5}
}
```

Build a structured data pack with source ledger:

```json
{
  "tool": "get_research_pack",
  "arguments": {"symbol": "603259", "history_days": 120, "announcement_limit": 10, "include_reports": false}
}
```

Get normalized announcement metadata and PDF URL:

```json
{
  "tool": "get_announcement_detail",
  "arguments": {
    "detail_url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=603259&announcementId=1225278835&orgId=9900035584&announcementTime=2026-05-07%2000:00:00",
    "include_text": false
  }
}
```

Get compact financial metrics:

```json
{
  "tool": "get_financial_summary",
  "arguments": {"symbol": "600519", "start_year": "2024"}
}
```

More examples are in [`examples/prompts.md`](examples/prompts.md).

## Cache

A small best-effort JSON cache is enabled by default:

- Default path: `~/.cache/a-share-mcp/`
- Override path: `A_SHARE_MCP_CACHE_DIR=/path/to/cache`
- Disable most cache behavior by setting very small TTLs in code or clearing the directory.

Tool responses include a `cache` object when served through the cache wrapper.

## Data sources

- Eastmoney public endpoints for quote and daily kline data.
- AkShare wrappers for A-share lists, financial indicators, business composition, CNINFO disclosure search, and research reports.

## Limitations

- Public endpoints can change, throttle, or return delayed data.
- Quote data can be unavailable outside market windows; a zero intraday value should not be treated as a real zero price.
- Financial indicator fields are source-defined; always verify report period and accounting scope.
- Broker research can be biased and should only be used as background material.
- This server does not execute trades, connect to broker accounts, or produce investment recommendations.

## License

MIT
