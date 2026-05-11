# A Share MCP

本项目是一个本地 stdio MCP server，把 A 股数据能力暴露给 Hermes / Claude / 其他 MCP client。

定位：

- 个人研究与学习用途；
- 给 AIIterate、BuJo research、LLM Wiki、LOA 审查流程提供 A 股数据工具；
- 不构成投资建议，不自动给买入/卖出结论。

## 当前能力

工具：

- `a_share_healthcheck`：检查 AkShare / Eastmoney 数据通路。
- `get_stock_profile`：个股基础资料。
- `get_realtime_quote`：行情快照、市值、PE/PB、行业等。
- `get_daily_history`：日线 OHLCV，支持 `none/qfq/hfq`。
- `get_financial_indicators`：财务指标表。
- `get_business_composition`：主营构成。
- `search_announcements`：巨潮 / 东方财富公告搜索。
- `search_research_reports`：东方财富个股研报搜索。注意研报只能做背景材料，不能当 canonical evidence。

数据源：

- Eastmoney public endpoints；
- AkShare 封装的 Sina / Eastmoney / CNINFO 数据接口。

## 运行

使用全局 Python 环境，不新建 venv：

```bash
/home/geekinney/.venv/global/bin/python /home/geekinney/vibe/a-share-mcp/scripts/a_share_mcp_server.py
```

## Hermes MCP 配置片段

加入 `~/.hermes/config.yaml`：

```yaml
mcp_servers:
  a_share:
    command: "/home/geekinney/.venv/global/bin/python"
    args: ["/home/geekinney/vibe/a-share-mcp/scripts/a_share_mcp_server.py"]
    timeout: 180
    connect_timeout: 60
```

重启 Hermes 后，工具名会变成类似：

```text
mcp_a_share_get_stock_profile
mcp_a_share_get_realtime_quote
mcp_a_share_get_daily_history
mcp_a_share_get_financial_indicators
mcp_a_share_get_business_composition
mcp_a_share_search_announcements
mcp_a_share_search_research_reports
```

## CLI smoke test

```bash
/home/geekinney/.venv/global/bin/python scripts/smoke_mcp.py
```

## AIIterate / BuJo / LLM Wiki 建议用法

推荐作为研究数据层，不作为投资决策器：

```text
AIIterate 问题/学习 session
→ A Share MCP 拉取行情、财务、公告、主营构成
→ 生成学习解释或研究草稿
→ LOA V2 审查关键数字和事实
→ BuJo research 保存长文
→ LLM Wiki 蒸馏公司/行业/概念知识
```

## 风险边界

A 股数据尤其要注意：

- 行情可能延迟；
- 财务口径可能是单季、累计、TTM、年报，不可混用；
- 价格必须说明复权方式；
- 概念板块噪音很大；
- 公告 PDF / 表格抽取可能不完整；
- 研报观点有立场，只能做辅助材料；
- 不输出自动买卖建议。
