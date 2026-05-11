"""A-share data adapters.

This module intentionally keeps data access deterministic and explicit.  It uses
AkShare for broad A-share coverage and a small Eastmoney HTTP fallback for quote
and daily kline data.  Returned values are JSON-serialisable and include source
metadata so downstream agents can cite data provenance.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import re
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable

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

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


DEFAULT_CACHE_DIR = Path(os.getenv("A_SHARE_MCP_CACHE_DIR", Path.home() / ".cache" / "a-share-mcp"))
DEFAULT_CACHE_TTL_SECONDS = _env_int("A_SHARE_MCP_CACHE_TTL_SECONDS", 300)


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
    if code.startswith(("8", "4")):
        return "BJ"
    return "SZ"


def eastmoney_secid(symbol: str) -> str:
    code = normalize_symbol(symbol)
    market = "1" if market_prefix(code) == "SH" else "0"
    # Eastmoney also uses market 0 for many Beijing-board endpoints in this
    # lightweight MVP.  If a BJ code fails, callers should treat it as source
    # unavailable rather than a definitive absence of data.
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


def _cache_key(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    raw = json.dumps({"name": name, "args": args, "kwargs": kwargs}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _cache_get(key: str, ttl_seconds: int) -> tuple[Any | None, float | None]:
    if ttl_seconds <= 0:
        return None, None
    path = DEFAULT_CACHE_DIR / f"{key}.json"
    try:
        if not path.exists():
            return None, None
        age = time.time() - path.stat().st_mtime
        if age > ttl_seconds:
            return None, None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), age
    except Exception:
        return None, None


def _cache_set(key: str, value: Any) -> None:
    try:
        DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = DEFAULT_CACHE_DIR / f"{key}.json"
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        tmp.replace(path)
    except Exception:
        pass


def cached(ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Small JSON cache for public data endpoints.

    Cache is best-effort and intentionally transparent: cached responses include
    a ``cache`` object with age/ttl metadata.
    """

    def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            key = _cache_key(fn.__name__, args, kwargs)
            cached_value, age = _cache_get(key, ttl_seconds)
            if isinstance(cached_value, dict):
                cached_value = dict(cached_value)
                cached_value["cache"] = {"hit": True, "ttl_seconds": ttl_seconds, "age_seconds": round(age or 0, 3)}
                return cached_value
            value = fn(*args, **kwargs)
            if isinstance(value, dict) and value.get("ok") is True:
                _cache_set(key, value)
            value = dict(value)
            value["cache"] = {"hit": False, "ttl_seconds": ttl_seconds, "age_seconds": 0}
            return value

        return wrapper

    return decorator


@cached(ttl_seconds=24 * 3600)
def search_stock(keyword: str, limit: int = 10) -> dict[str, Any]:
    """Search A-share codes by symbol or Chinese company/security name."""
    if not keyword or not keyword.strip():
        raise ValueError("keyword is required")
    kw = keyword.strip().upper()
    aks = require_akshare()
    df = aks.stock_info_a_code_name()
    df = df.rename(columns={"code": "symbol", "name": "name"})
    joined = df.astype(str).agg(" ".join, axis=1).str.upper()
    matches = df[joined.str.contains(re.escape(kw), na=False)]
    if matches.empty and re.search(r"\d{2,6}", kw):
        matches = df[df["symbol"].astype(str).str.contains(re.escape(re.search(r"\d+", kw).group(0)), na=False)]
    records = []
    for row in df_to_records(matches, limit=limit):
        symbol = normalize_symbol(str(row["symbol"]))
        records.append({"symbol": symbol, "name": row.get("name"), "market": market_prefix(symbol)})
    return {
        "ok": True,
        "keyword": keyword,
        "source": "akshare.stock_info_a_code_name",
        "count": len(records),
        "records": records,
    }


@cached(ttl_seconds=6 * 3600)
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


@cached(ttl_seconds=60)
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


@cached(ttl_seconds=3600)
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


@cached(ttl_seconds=24 * 3600)
def get_financial_indicators(symbol: str, start_year: str | int = "2023", limit: int = 12) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    aks = require_akshare()
    df = aks.stock_financial_analysis_indicator(symbol=code, start_year=str(start_year))
    return {
        "ok": True,
        "symbol": code,
        "source": "akshare.stock_financial_analysis_indicator/sina",
        "start_year": str(start_year),
        "count": min(len(df), limit),
        "columns": [str(c) for c in df.columns],
        "records": df_to_records(df, limit=limit),
    }


@cached(ttl_seconds=24 * 3600)
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


def _select_latest_financial_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return sorted(records, key=lambda r: str(r.get("日期") or ""), reverse=True)[0]


def _pick(record: dict[str, Any] | None, keys: list[str]) -> dict[str, Any]:
    if not record:
        return {}
    return {k: record.get(k) for k in keys if k in record}


@cached(ttl_seconds=24 * 3600)
def get_financial_summary(symbol: str, start_year: str | int = "2024") -> dict[str, Any]:
    indicators = get_financial_indicators(symbol, start_year=start_year, limit=8)
    latest = _select_latest_financial_record(indicators.get("records", []))
    key_metrics = _pick(
        latest,
        [
            "日期",
            "摊薄每股收益(元)",
            "加权每股收益(元)",
            "每股净资产_调整后(元)",
            "每股经营性现金流(元)",
            "主营业务收入增长率(%)",
            "净利润增长率(%)",
            "净资产收益率(%)",
            "加权净资产收益率(%)",
            "销售净利率(%)",
            "营业利润率(%)",
            "资产负债率(%)",
            "流动比率",
            "速动比率",
            "经营现金净流量与净利润的比率(%)",
            "总资产(元)",
        ],
    )
    return {
        "ok": True,
        "symbol": normalize_symbol(symbol),
        "source": indicators.get("source"),
        "start_year": str(start_year),
        "latest_period": latest.get("日期") if latest else None,
        "key_metrics": key_metrics,
        "record_count": indicators.get("count"),
        "warning": "Financial fields are source-defined; verify report period and accounting scope before using in investment research.",
    }


@cached(ttl_seconds=3600)
def search_announcements(symbol: str, keyword: str = "", start_date: str | None = None, end_date: str | None = None, category: str = "", limit: int = 20) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    aks = require_akshare()
    start = (start_date or (_dt.date.today() - _dt.timedelta(days=365)).strftime("%Y%m%d")).replace("-", "")
    end = (end_date or _today_yyyymmdd()).replace("-", "")
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
            df = df[joined.str.contains(keyword, case=False, regex=False, na=False)]
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


@cached(ttl_seconds=6 * 3600)
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


def _history_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    closes = [float(r["close"]) for r in records]
    latest = records[-1]
    stats = {
        "latest_date": latest.get("date"),
        "latest_close": latest.get("close"),
        "period_high": max(closes),
        "period_low": min(closes),
        "return_pct": round((closes[-1] / closes[0] - 1) * 100, 4) if closes[0] else None,
    }
    for n in (5, 10, 20, 60):
        if len(closes) >= n:
            window = closes[-n:]
            stats[f"ma{n}"] = round(sum(window) / n, 4)
            stats[f"return_{n}d_pct"] = round((closes[-1] / closes[-n] - 1) * 100, 4) if closes[-n] else None
    return stats


@cached(ttl_seconds=3600)
def get_company_snapshot(symbol: str, history_days: int = 60, announcement_limit: int = 5) -> dict[str, Any]:
    """Return an agent-friendly research pack for one A-share company."""
    code = normalize_symbol(symbol)
    history_days = max(5, min(int(history_days), 250))
    announcement_limit = max(1, min(int(announcement_limit), 20))
    quote = get_realtime_quote(code)
    profile = get_stock_profile(code)
    history = get_daily_history(code, limit=history_days)
    financial = get_financial_summary(code)
    try:
        business = get_business_composition(code, limit=10)
    except Exception as exc:
        business = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    announcements = search_announcements(code, limit=max(1, min(int(announcement_limit), 20)))
    return {
        "ok": True,
        "symbol": code,
        "name": quote.get("quote", {}).get("name") or profile.get("profile", {}).get("股票简称"),
        "market": market_prefix(code),
        "sources": {
            "quote": quote.get("source"),
            "profile": profile.get("source"),
            "history": history.get("source"),
            "financial": financial.get("source"),
            "business": business.get("source"),
            "announcements": announcements.get("source"),
        },
        "quote": quote.get("quote"),
        "profile": profile.get("profile"),
        "price_history_stats": _history_stats(history.get("records", [])),
        "financial_summary": financial.get("key_metrics"),
        "business_composition_sample": business.get("records", [])[:10] if business.get("ok") else [],
        "recent_announcements": announcements.get("records", [])[:announcement_limit],
        "warnings": [
            "For research only; not investment advice.",
            "Public endpoints can be delayed or unavailable; verify important figures against official filings.",
            "Price history adjustment mode defaults to qfq when using get_daily_history directly.",
        ],
    }


def data_healthcheck() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "akshare_available": ak is not None,
        "akshare_import_error": _AKSHARE_IMPORT_ERROR,
        "cache_dir": str(DEFAULT_CACHE_DIR),
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
