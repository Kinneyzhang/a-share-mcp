# A Share MCP Design

## Vision

Expose reliable, source-labeled A-share data tools as a local stdio MCP server, so agents can build A-share research workflows without hard-coding finance data scraping into each app.

## Product positioning

A Share MCP is not trying to be the largest financial data MCP. It is a lightweight, no-token-required research data layer for Chinese A-share workflows:

```text
Agent question / research draft
→ source-labeled A-share data tools
→ report writing / learning explanation
→ optional fact audit / human review
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
small JSON cache + AkShare + Eastmoney public APIs + CNINFO through AkShare
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
- Research report search.
- One-call company snapshot.
- Best-effort JSON cache.
- MCP initialize/list/call smoke test.
- Public README, license, package metadata, CI, examples.

## Future extensions

- Industry peer discovery.
- Index / sector component data.
- Convertible bonds / funds.
- Announcement PDF download and text extraction.
- Source-pack export for deterministic fact audit.
- AIIterate job adapter.
- LLM Wiki company/entity distillation.
