# A Share MCP Design

## Vision

Expose reliable, source-labeled A-share data tools as a local stdio MCP server, so agents can build A-share research workflows without hard-coding finance data scraping into each app.

## Non-goals

- No investment advice.
- No automatic trading.
- No account/broker integration.
- No claim that public/free data equals professional Wind/iFinD quality.
- No silent data cleaning that hides source/date/口径.

## Architecture

```text
MCP client
  ↓ stdio JSON-RPC
scripts/a_share_mcp_server.py
  ↓
a_share_mcp.server
  ↓
a_share_mcp.data
  ↓
AkShare + Eastmoney public APIs + CNINFO through AkShare
```

## Tool design principles

1. Every tool returns `source`.
2. Date, adjust mode, category, and count are explicit.
3. Financial tables preserve Chinese column names because they encode business meaning.
4. Research reports are marked as biased background material.
5. Errors are returned as structured JSON text content, not swallowed.

## MVP scope

- Company profile.
- Quote snapshot.
- Daily history.
- Financial indicators.
- Business composition.
- Announcement search.
- Research report search.
- MCP initialize/list/call smoke test.

## Future extensions

- Industry peer discovery.
- Index / sector component data.
- Convertible bonds / funds.
- Announcement PDF download and text extraction.
- Source-pack export for LOA deterministic audit.
- AIIterate job adapter.
- LLM Wiki company/entity distillation.
