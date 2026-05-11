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
2. Composite and v1-style tools prefer `source_ledger` and `data_quality` metadata.
3. Date, adjust mode, category, and count are explicit.
4. Financial raw tables preserve Chinese column names because they encode business meaning.
5. Agent-facing summary tools reduce table noise.
6. Research reports are marked as biased background material.
7. Partial failures should be isolated when possible, especially batch and composite calls.
8. Errors are returned as structured JSON text content, not swallowed.

## v1.x stable scope

- Company/security search.
- Company profile.
- Quote snapshot and batch quotes.
- Daily history with Eastmoney primary source and AkShare/Sina fallback.
- Raw financial indicators, summary, and trend extraction.
- Business composition.
- Announcement search, detail metadata, PDF URL, text preview, OCR fallback, and page layout extraction.
- Announcement keyword classification.
- Research report search.
- Company snapshot, structured research pack, batch snapshots, and market overview.
- Industry peer discovery and peer comparison.
- Index, sector snapshot, and sector components.
- Financial event pack: dividend, repurchase, shareholder change, financing, restricted-share release.
- Best-effort JSON cache with status and clear operations.
- MCP initialize/list/call smoke test plus optional live v1 smoke test.
- Public README, Chinese README, license, package metadata, changelog, migration guide, examples, and CI.

## Compatibility policy

Starting from v1.0.0:

- Patch releases fix bugs and should not intentionally remove response fields.
- Minor releases may add tools, optional parameters, or response fields.
- Breaking changes require a new major version and migration notes.

## Future extensions

- More robust financial statement normalization.
- Better table reconstruction from announcement PDFs.
- Optional additional data-source adapters while keeping no-token defaults.
- Export formats for downstream tools.
- Optional integration examples kept outside the core MCP server.
