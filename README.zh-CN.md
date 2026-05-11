# A Share MCP

[English](README.md) | [简体中文](README.zh-CN.md)

面向 AI Agent 的 A 股数据 MCP：轻量、无需 token、强调来源标注和结构化数据输出。

A Share MCP 不是交易系统，也不是荐股工具。它把 A 股行情、日线、财务指标、主营构成、公告、研报背景材料和公司研究数据包暴露为本地 stdio MCP 工具，方便 Claude Desktop、Hermes、Cursor 等 MCP client 调用。

> 仅供研究和学习使用，不构成投资建议，不提供自动买卖、券商账户接入或交易信号。

## 项目定位

已有很多大而全的金融 MCP。本项目刻意保持轻量，强调：

- **MVP 无需 token**：使用 Eastmoney public endpoints 与 AkShare 封装数据源。
- **每个工具带来源**：返回 `source` 字段，便于引用、复核和问题定位。
- **Agent 友好**：提供 `get_financial_summary` 和 `get_company_snapshot`，减少原始财务大表噪音。
- **本地优先 stdio MCP**：适合 Claude Desktop、Hermes、Cursor 等 MCP client 本地调用。
- **保守边界**：公共数据可能延迟、缺失或接口变化，关键结论必须回到官方公告核验。

## 工具列表

- `a_share_healthcheck`：检查 AkShare / Eastmoney 数据通路。
- `search_stock`：按中文名或代码搜索 A 股证券。
- `get_stock_profile`：个股基础资料。
- `get_realtime_quote`：行情快照、市值、PE/PB、行业等。
- `get_daily_history`：日线 OHLCV，支持 `none/qfq/hfq`。
- `get_financial_indicators`：原始财务指标表。
- `get_financial_summary`：Agent 友好的核心财务摘要。
- `get_business_composition`：主营构成。
- `search_announcements`：巨潮 / 东方财富公告搜索，返回标准化公告 ID、详情链接和 PDF 链接。
- `get_announcement_detail`：解析/标准化巨潮公告详情链接，可选提取限定长度 PDF 文本预览，并返回文本质量指标；安装 OCR extra 后支持自动 OCR fallback。
- `search_research_reports`：东方财富个股研报搜索，仅作背景材料。
- `get_company_snapshot`：一站式公司研究数据包：行情、资料、价格统计、财务摘要、主营构成、近期公告。
- `get_research_pack`：结构化公司数据包，包含价格记录、财务、主营构成、公告、可选研报和 source ledger。
- `get_industry_peers`：同行业 A 股 peers，含估值、市值等字段。
- `get_peer_comparison`：与同业 peer set 做简单百分位比较。
- `get_index_snapshot`：A 股主要指数行情快照。
- `get_sector_snapshot`：行业/概念板块列表。
- `get_sector_components`：行业/概念板块成分股。
- `get_financial_events_pack`：分红、回购、股东增减持/权益变动、融资、限售解禁事件包。
- `get_dividend_events` / `get_repurchase_events` / `get_shareholder_change_events` / `get_financing_events` / `get_restricted_release_events`：单类事件工具。
- `get_announcement_layout`：公告 PDF 页面版式抽取，支持 OCR 行或内嵌文本块。

## 安装

```bash
git clone https://github.com/Kinneyzhang/a-share-mcp.git
cd a-share-mcp
python -m pip install -e .
```

如需公告 PDF 自动 OCR fallback：

```bash
python -m pip install -e '.[ocr]'
```

运行 MCP server：

```bash
a-share-mcp
```

或直接从源码运行：

```bash
python scripts/a_share_mcp_server.py
```

## MCP 客户端配置

配置时建议使用绝对路径：

```yaml
mcp_servers:
  a_share:
    command: "python"
    args: ["/ABSOLUTE/PATH/TO/a-share-mcp/scripts/a_share_mcp_server.py"]
    timeout: 180
    connect_timeout: 60
```

如果已安装 console script：

```yaml
mcp_servers:
  a_share:
    command: "a-share-mcp"
    args: []
    timeout: 180
    connect_timeout: 60
```

不同 MCP client 会给工具名加前缀，例如 Hermes 中可能是：

```text
mcp_a_share_get_company_snapshot
```

## Smoke test

适合 CI 的确定性协议测试：

```bash
python -m py_compile a_share_mcp/*.py scripts/*.py
python scripts/protocol_smoke.py
```

本地发布前可选跑真实数据 smoke test：

```bash
python scripts/smoke_mcp.py
```

真实数据测试成功输出类似：

```json
{
  "ok": true,
  "tools": 13,
  "quote_name": "贵州茅台"
}
```

## 示例

按中文名搜索：

```json
{
  "tool": "search_stock",
  "arguments": {"keyword": "药明康德", "limit": 5}
}
```

生成公司研究数据包：

```json
{
  "tool": "get_company_snapshot",
  "arguments": {"symbol": "603259", "history_days": 60, "announcement_limit": 5}
}
```

生成带 source ledger 的结构化数据包：

```json
{
  "tool": "get_research_pack",
  "arguments": {"symbol": "603259", "history_days": 120, "announcement_limit": 10, "include_reports": false}
}
```

获取公告详情元数据和 PDF 链接：

```json
{
  "tool": "get_announcement_detail",
  "arguments": {
    "detail_url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=603259&announcementId=1225278835&orgId=9900035584&announcementTime=2026-05-07%2000:00:00",
    "include_text": false
  }
}
```

获取财务摘要：

```json
{
  "tool": "get_financial_summary",
  "arguments": {"symbol": "600519", "start_year": "2024"}
}
```

更多示例见 [`examples/prompts.md`](examples/prompts.md)。

## 缓存

内置一个轻量 JSON cache：

- 默认路径：`~/.cache/a-share-mcp/`
- 可用 `A_SHARE_MCP_CACHE_DIR=/path/to/cache` 改路径
- 工具响应中会包含 `cache` 元信息

## 数据源

- Eastmoney public endpoints：行情与日线。
- AkShare：A 股列表、财务指标、主营构成、巨潮公告搜索、研报搜索等。

## 限制与风险

- 公共接口可能延迟、限流、变更或临时不可用。
- 非交易时段行情字段可能异常，不能把 `0` 当成真实价格。
- 财务字段来自数据源定义，使用前要确认报告期、累计/单季/TTM 口径。
- 公告 PDF 文本抽取是 best-effort；`text_mode=auto` 会先尝试 PDF 内嵌文本，遇到空文本或疑似乱码时再走 OCR fallback。当 `text_status` 为 `poor_quality` 时，不能把 `text` 当成可靠全文，应以 `pdf_url` 原文为准。
- 同业比较只是数据摘要，不是估值判断或投资评级。
- 本项目不执行交易、不接券商账户、不生成买卖建议。

## License

MIT
