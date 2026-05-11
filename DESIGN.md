# A Share MCP Design

## Vision

Expose reliable, source-labeled A-share data tools as a local stdio MCP server, so agents can access A-share data without hard-coding finance data scraping into each app.

## Product positioning

A Share MCP is not trying to be the largest financial data MCP. It is a lightweight, no-token-required data layer for Chinese A-share tools:

```text
MCP client
→ source-labeled A-share data tools
→ structured JSON results
```

## Non-goals

- No investment advice.
- No automatic trading.
- No account/broker integration.
- No claim that public/free data equals professional Wind/iFinD quality.
- No silent data cleaning that hides source/date/口径.

## Architecture

```text
MCP client
  ↓ stdio JSON-RPC / JSONL
scripts/a_share_mcp_server.py or console script a-share-mcp
  ↓
a_share_mcp.server
  ↓
a_share_mcp.data
  ↓
small JSON cache + AkShare + Eastmoney public APIs + CNINFO public search/PDF endpoints
```

## Tool design principles

1. Every tool returns `source`.
2. Date, adjust mode, category, and count are explicit.
3. Financial raw tables preserve Chinese column names because they encode business meaning.
4. Agent-facing summary tools reduce table noise.
5. Research reports are marked as biased background material.
6. Errors are returned as structured JSON text content, not swallowed.

## v0.1.0 scope

- Company/security search.
- Company profile.
- Quote snapshot.
- Daily history.
- Raw financial indicators.
- Financial summary.
- Business composition.
- Announcement search.
- Normalized announcement detail metadata, canonical PDF URLs, and bounded best-effort PDF text extraction.
- Research report search.
- One-call company snapshot.
- Structured research/data pack with source ledger.
- Best-effort JSON cache.
- MCP initialize/list/call smoke test.
- Public README, license, package metadata, CI, examples.

## Future extensions

- Industry peer discovery.
- Index / sector component data.
- Convertible bonds / funds.
- Announcement PDF text quality scoring for difficult scanned/embedded-font filings.
- Export formats for downstream tools.
- Optional integration examples kept outside the core MCP server.
