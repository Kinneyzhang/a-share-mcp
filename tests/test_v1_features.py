import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from a_share_mcp import data


class V1FeatureTests(unittest.TestCase):
    def test_quality_envelope_adds_source_ledger_and_freshness(self):
        payload = {"ok": True, "source": "unit.source", "warnings": ["already"]}
        out = data.with_quality_metadata(payload, tool="unit_tool")
        self.assertTrue(out["ok"])
        self.assertEqual(out["tool"], "unit_tool")
        self.assertIn("source_ledger", out)
        self.assertEqual(out["source_ledger"][0]["source"], "unit.source")
        self.assertIn("data_quality", out)
        self.assertIn("as_of", out["data_quality"])
        self.assertIn("For research and education only; not investment advice.", out["warnings"])

    def test_batch_get_quotes_preserves_partial_failures(self):
        def fake_quote(symbol):
            if symbol == "000000":
                raise RuntimeError("boom")
            return {"ok": True, "symbol": symbol, "source": "fake.quote", "quote": {"symbol": symbol}}

        with patch.object(data, "get_realtime_quote", side_effect=fake_quote):
            out = data.batch_get_quotes(["600519", "000000"])

        self.assertTrue(out["ok"])
        self.assertTrue(out["partial"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["errors"][0]["symbol"], "000000")
        self.assertEqual(out["records"][0]["symbol"], "600519")

    def test_compare_companies_returns_per_metric_percentiles(self):
        quotes = {
            "600001": {"ok": True, "symbol": "600001", "source": "fake", "quote": {"symbol": "600001", "name": "A", "total_market_cap": 100, "pe_ttm": 10}},
            "600002": {"ok": True, "symbol": "600002", "source": "fake", "quote": {"symbol": "600002", "name": "B", "total_market_cap": 300, "pe_ttm": 30}},
            "600003": {"ok": True, "symbol": "600003", "source": "fake", "quote": {"symbol": "600003", "name": "C", "total_market_cap": 200, "pe_ttm": 20}},
        }
        with patch.object(data, "get_realtime_quote", side_effect=lambda symbol: quotes[symbol]):
            out = data.compare_companies(["600001", "600002", "600003"], metrics="total_market_cap,pe_ttm")

        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 3)
        ranks = {r["symbol"]: r["metrics"]["total_market_cap"]["rank_desc"] for r in out["records"]}
        self.assertEqual(ranks["600002"], 1)
        self.assertEqual(ranks["600001"], 3)

    def test_financial_trends_uses_existing_indicators(self):
        fake = {
            "ok": True,
            "source": "fake.financials",
            "records": [
                {"日期": "2024-12-31", "净利润同比增长率(%)": 10, "营业收入同比增长率(%)": 20, "资产负债率(%)": 30},
                {"日期": "2023-12-31", "净利润同比增长率(%)": 5, "营业收入同比增长率(%)": 15, "资产负债率(%)": 40},
            ],
        }
        with patch.object(data, "get_financial_indicators", return_value=fake):
            out = data.get_financial_trends("600519")

        self.assertTrue(out["ok"])
        self.assertEqual(out["symbol"], "600519")
        self.assertIn("profitability", out["trends"])
        self.assertEqual(out["latest_period"], "2024-12-31")

    def test_classify_announcements_groups_keywords(self):
        fake = {
            "ok": True,
            "source": "fake.announcements",
            "records": [
                {"title": "2025年年度报告"},
                {"title": "关于股份回购进展公告"},
                {"title": "关于股东减持计划公告"},
                {"title": "关于分红派息实施公告"},
            ],
        }
        with patch.object(data, "search_announcements", return_value=fake):
            out = data.classify_announcements("600519", limit=4)

        self.assertTrue(out["ok"])
        self.assertEqual(out["categories"]["periodic_report"]["count"], 1)
        self.assertEqual(out["categories"]["repurchase"]["count"], 1)
        self.assertEqual(out["categories"]["shareholder_change"]["count"], 1)
        self.assertEqual(out["categories"]["dividend"]["count"], 1)

    def test_cache_status_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "a.json").write_text("{}", encoding="utf-8")
            (cache_dir / "b.json").write_text("{}", encoding="utf-8")
            with patch.object(data, "DEFAULT_CACHE_DIR", cache_dir):
                status = data.get_cache_status()
                self.assertEqual(status["file_count"], 2)
                cleared = data.clear_cache()
                self.assertEqual(cleared["removed_count"], 2)
                self.assertEqual(data.get_cache_status()["file_count"], 0)


if __name__ == "__main__":
    unittest.main()
