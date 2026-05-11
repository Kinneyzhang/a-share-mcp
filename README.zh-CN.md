# A Share MCP

[English](README.md) | [简体中文](README.zh-CN.md)

面向 AI Agent 研究工作流的 A 股数据 MCP：轻量、无需 token、强调来源标注和可审查数据输出。

A Share MCP 不是交易系统，也不是荐股工具。它把 A 股行情、日线、财务指标、主营构成、公告、研报背景材料和公司研究数据包暴露为本地 stdio MCP 工具，方便 Claude Desktop、Hermes、Cursor 等 MCP client 调用。

> 仅供研究和学习使用，不构成投资建议，不提供自动买卖、券商账户接入或交易信号。

## 项目定位

已有很多大而全的金融 MCP。本项目刻意保持轻量，强调：

- **MVP 无需 token**：使用 Eastmoney public endpoints 与 AkShare 封装数据源。
- **每个工具带来源**：返回 `source` 字段，便于后续事实审查、引用和复盘。
- **Agent 友好**：提供 `get_financial_summary` 和 `get_company_snapshot`，减少原始财务大表噪音。
- **本地优先 stdio MCP**：适合个人研究、AIIterate、BuJo research、LLM Wiki、LOA 审查工作流。
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
- `search_announcements`：巨潮 / 东方财富公告搜索。
- `search_research_reports`：东方财富个股研报搜索，仅作背景材料。
- `get_company_snapshot`：一站式公司研究数据包：行情、资料、价格统计、财务摘要、主营构成、近期公告。

## 安装

```bash
git clone https://github.com/Kinneyzhang/a-share-mcp.git
cd a-share-mcp
python -m pip install -e .
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
  "tools": 11,
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
- 研报观点可能有立场，只能做背景材料。
- 本项目不执行交易、不接券商账户、不生成买卖建议。

## License

MIT
