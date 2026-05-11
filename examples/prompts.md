# Example prompts

Use these prompts with an MCP-capable agent after configuring `a-share-mcp`.

## Company data pack with source ledger

```text
Use A Share MCP to get a structured data pack for 603259 药明康德. Include price statistics, financial summary, business composition, announcements, and source ledger. Do not give buy/sell advice.
```

Expected tool:

```json
{
  "tool": "get_research_pack",
  "arguments": {"symbol": "603259", "history_days": 120, "announcement_limit": 10, "include_reports": false}
}
```

## Company research snapshot

```text
Use A Share MCP to build a research snapshot for 603259 药明康德. Include latest quote, 60-day trend, core financial summary, recent announcements, and key risks. Do not give buy/sell advice.
```

Expected tool:

```json
{
  "tool": "get_company_snapshot",
  "arguments": {"symbol": "603259", "history_days": 60, "announcement_limit": 5}
}
```

## Search by Chinese name

```text
Find the A-share code for 贵州茅台, then fetch its quote and business composition.
```

Expected tools:

```json
{"tool": "search_stock", "arguments": {"keyword": "贵州茅台", "limit": 5}}
{"tool": "get_realtime_quote", "arguments": {"symbol": "600519"}}
{"tool": "get_business_composition", "arguments": {"symbol": "600519", "limit": 10}}
```

## Announcement-driven research

```text
Search recent CNINFO announcements for 宁德时代 and summarize which filings deserve manual review. Treat announcement links as primary evidence.
```

Expected tool:

```json
{
  "tool": "search_announcements",
  "arguments": {"symbol": "300750", "start_date": "20260101", "limit": 10}
}
```

## Financial summary

```text
Fetch the latest financial summary for 600519 since 2024. Explain revenue growth, profit growth, ROE, leverage, and operating cash-flow quality. Do not provide investment advice.
```

Expected tool:

```json
{"tool": "get_financial_summary", "arguments": {"symbol": "600519", "start_year": "2024"}}
```
