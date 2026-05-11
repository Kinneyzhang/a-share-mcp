"""A-share data adapters.

This module intentionally keeps data access deterministic and explicit.  It uses
AkShare for broad A-share coverage and a small Eastmoney HTTP fallback for quote
and daily kline data.  Returned values are JSON-serialisable and include source
metadata so downstream agents can cite data provenance.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any

import pandas as pd
import requests

try:
    import akshare as ak
except Exception as exc:  # pragma: no cover - runtime diagnostic path
    ak = None  # type: ignore[assignment]
    _AKSHARE_IMPORT_ERROR = repr(exc)
else:
    _AKSHARE_IMPORT_ERROR = None

EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _today_yyyymmdd() -> str:
    return _dt.date.today().strftime("%Y%m%d")


def normalize_symbol(symbol: str) -> str:
    """Return a six-digit A-share code from common inputs.

    Accepts forms like ``600519``, ``SH600519``, ``600519.SH``.
    """
    if not symbol:
        raise ValueError("symbol is required")
    s = symbol.strip().upper()
    match = re.search(r"(\d{6})", s)
    if not match:
        raise ValueError(f"invalid A-share symbol: {symbol!r}")
    return match.group(1)


def market_prefix(symbol: str) -> str:
    code = normalize_symbol(symbol)
    if code.startswith(("6", "9")):
        return "SH"
    return "SZ"


def eastmoney_secid(symbol: str) -> str:
    code = normalize_symbol(symbol)
    market = "1" if market_prefix(code) == "SH" else "0"
    return f"{market}.{code}"


def _clean_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, _dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if hasattr(value, "item"):
        try:
            return _clean_scalar(value.item())
        except Exception:
            pass
    return value


def df_to_records(df: pd.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in df.head(max(0, limit)).to_dict("records"):
        rows.append({str(k): _clean_scalar(v) for k, v in record.items()})
    return rows


def require_akshare() -> Any:
    if ak is None:
        raise RuntimeError(f"akshare is not available: {_AKSHARE_IMPORT_ERROR}")
    return ak


def get_stock_profile(symbol: str) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    try:
        aks = require_akshare()
        df = aks.stock_individual_info_em(symbol=code)
        profile = {str(row["item"]): _clean_scalar(row["value"]) for _, row in df.iterrows()}
        return {
            "ok": True,
            "symbol": code,
            "market": market_prefix(code),
            "source": "akshare.stock_individual_info_em/eastmoney",
            "profile": profile,
        }
    except Exception as exc:
        # Eastmoney's profile endpoint is occasionally flaky.  Fall back to the
        # quote endpoint so the tool still returns the company name/industry and
        # a clear warning instead of silently failing.
        quote = get_realtime_quote(code)
        q = quote.get("quote", {})
        return {
            "ok": True,
            "symbol": code,
            "market": market_prefix(code),
            "source": "eastmoney.push2.ulist fallback",
            "warning": f"profile endpoint failed: {type(exc).__name__}: {str(exc)[:160]}",
            "profile": {
                "股票代码": code,
                "股票简称": q.get("name"),
                "行业": q.get("industry"),
                "总市值": q.get("total_market_cap"),
                "流通市值": q.get("float_market_cap"),
                "市盈率TTM": q.get("pe_ttm"),
                "市净率": q.get("pb"),
            },
        }


def get_realtime_quote(symbol: str) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    fields = "f12,f14,f2,f3,f4,f5,f6,f7,f15,f16,f17,f18,f20,f21,f23,f8,f9,f10,f13,f100,f124"
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt": "2", "secids": eastmoney_secid(code), "fields": fields}
    r = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=20)
    r.raise_for_status()
    payload = r.json()
    diff = (((payload or {}).get("data") or {}).get("diff") or [])
    if not diff:
        raise RuntimeError(f"no quote data returned for {code}")
    q = diff[0]
    # Eastmoney can return 0.0 for current intraday fields outside available windows;
    # keep previous close and timestamp to avoid pretending a zero price is a real quote.
    quote = {
        "code": q.get("f12"),
        "name": q.get("f14"),
        "price": q.get("f2"),
        "change_pct": q.get("f3"),
        "change": q.get("f4"),
        "volume": q.get("f5"),
        "turnover": q.get("f6"),
        "amplitude_pct": q.get("f7"),
        "high": q.get("f15"),
        "low": q.get("f16"),
        "open": q.get("f17"),
        "prev_close": q.get("f18"),
        "total_market_cap": q.get("f20"),
        "float_market_cap": q.get("f21"),
        "pb": q.get("f23"),
        "turnover_rate_pct": q.get("f8"),
        "pe_ttm": q.get("f9"),
        "volume_ratio": q.get("f10"),
        "industry": q.get("f100"),
        "quote_timestamp": q.get("f124"),
    }
    return {
        "ok": True,
        "symbol": code,
        "market": market_prefix(code),
        "source": "eastmoney.push2.ulist",
        "note": "If intraday fields are 0, treat them as unavailable rather than a real zero price.",
        "quote": quote,
    }


def get_daily_history(symbol: str, start_date: str | None = None, end_date: str | None = None, adjust: str = "qfq", limit: int = 60) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    start = (start_date or "20200101").replace("-", "")
    end = (end_date or _today_yyyymmdd()).replace("-", "")
    adjust_map = {"none": "0", "qfq": "1", "hfq": "2"}
    fqt = adjust_map.get(adjust, "1")
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": eastmoney_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": fqt,
        "beg": start,
        "end": end,
        "lmt": str(max(1, min(int(limit), 500))),
    }
    r = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=20)
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or {}
    rows = []
    for line in data.get("klines") or []:
        parts = line.split(",")
        if len(parts) >= 11:
            rows.append(
                {
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "turnover": float(parts[6]),
                    "amplitude_pct": float(parts[7]),
                    "change_pct": float(parts[8]),
                    "change": float(parts[9]),
                    "turnover_rate_pct": float(parts[10]),
                }
            )
    return {
        "ok": True,
        "symbol": code,
        "name": data.get("name"),
        "market": market_prefix(code),
        "source": "eastmoney.push2his.kline",
        "adjust": adjust,
        "start_date": start,
        "end_date": end,
        "count": len(rows),
        "records": rows,
    }


def get_financial_indicators(symbol: str, start_year: str | int = "2023", limit: int = 12) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    aks = require_akshare()
    df = aks.stock_financial_analysis_indicator(symbol=code, start_year=str(start_year))
    # Keep full rows because Chinese column names are useful for analysts, but cap row count.
    return {
        "ok": True,
        "symbol": code,
        "source": "akshare.stock_financial_analysis_indicator/sina",
        "start_year": str(start_year),
        "count": min(len(df), limit),
        "columns": [str(c) for c in df.columns],
        "records": df_to_records(df, limit=limit),
    }


def get_business_composition(symbol: str, limit: int = 30) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    aks = require_akshare()
    prefixed = f"{market_prefix(code)}{code}"
    df = aks.stock_zygc_em(symbol=prefixed)
    return {
        "ok": True,
        "symbol": code,
        "source": "akshare.stock_zygc_em/eastmoney",
        "count": min(len(df), limit),
        "records": df_to_records(df, limit=limit),
    }


def search_announcements(symbol: str, keyword: str = "", start_date: str | None = None, end_date: str | None = None, category: str = "", limit: int = 20) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    aks = require_akshare()
    start = (start_date or (_dt.date.today() - _dt.timedelta(days=365)).strftime("%Y%m%d")).replace("-", "")
    end = (end_date or _today_yyyymmdd()).replace("-", "")
    # Prefer CNINFO for announcement text/PDF provenance; fallback to Eastmoney individual notice API.
    try:
        df = aks.stock_zh_a_disclosure_report_cninfo(
            symbol=code,
            market="沪深京",
            keyword=keyword or "",
            category=category or "",
            start_date=start,
            end_date=end,
        )
        source = "akshare.stock_zh_a_disclosure_report_cninfo/cninfo"
    except Exception:
        df = aks.stock_individual_notice_report(security=code, symbol=category or "全部", begin_date=start, end_date=end)
        if keyword:
            joined = df.astype(str).agg(" ".join, axis=1)
            df = df[joined.str.contains(keyword, case=False, na=False)]
        source = "akshare.stock_individual_notice_report/eastmoney"
    return {
        "ok": True,
        "symbol": code,
        "source": source,
        "keyword": keyword,
        "category": category,
        "start_date": start,
        "end_date": end,
        "count": min(len(df), limit),
        "records": df_to_records(df, limit=limit),
    }


def search_research_reports(symbol: str, limit: int = 20) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    aks = require_akshare()
    df = aks.stock_research_report_em(symbol=code)
    return {
        "ok": True,
        "symbol": code,
        "source": "akshare.stock_research_report_em/eastmoney",
        "count": min(len(df), limit),
        "records": df_to_records(df, limit=limit),
        "warning": "Broker research can be biased; use as background material, not as canonical evidence.",
    }


def data_healthcheck() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "akshare_available": ak is not None,
        "akshare_import_error": _AKSHARE_IMPORT_ERROR,
        "checks": {},
    }
    try:
        result["checks"]["quote_600519"] = get_realtime_quote("600519")["ok"]
    except Exception as exc:
        result["ok"] = False
        result["checks"]["quote_600519"] = repr(exc)
    try:
        hist = get_daily_history("600519", start_date="20260501", limit=3)
        result["checks"]["history_600519_count"] = hist.get("count")
    except Exception as exc:
        result["ok"] = False
        result["checks"]["history_600519"] = repr(exc)
    return result
