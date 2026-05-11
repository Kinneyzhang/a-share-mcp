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
import io
import os
import re
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

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
CACHE_SCHEMA_VERSION = "5"


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
    # Eastmoney quote/kline secid convention used by these public endpoints:
    # 1 = Shanghai, 0 = Shenzhen/Beijing.  Beijing-board symbols commonly start
    # with 4 or 8 and resolve under market 0 for the endpoints used here.
    market = "1" if market_prefix(code) == "SH" else "0"
    return f"{market}.{code}"


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def clean_text(value: Any, max_len: int = 120) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    return text[:max_len]


def clean_date(value: Any, default: str) -> str:
    text = clean_text(value, max_len=16).replace("-", "")
    return text if re.fullmatch(r"\d{8}", text) else default


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


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
    raw = json.dumps({"cache_schema": CACHE_SCHEMA_VERSION, "name": name, "args": args, "kwargs": kwargs}, ensure_ascii=False, sort_keys=True, default=str)
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
            if isinstance(value, dict) and value.get("ok") is True and value.get("partial") is not True:
                _cache_set(key, value)
            value = dict(value)
            value["cache"] = {"hit": False, "ttl_seconds": ttl_seconds, "age_seconds": 0}
            return value

        return wrapper

    return decorator


@cached(ttl_seconds=24 * 3600)
def search_stock(keyword: str, limit: int = 10) -> dict[str, Any]:
    """Search A-share codes by symbol or Chinese company/security name."""
    keyword = clean_text(keyword, max_len=80)
    limit = clamp_int(limit, default=10, minimum=1, maximum=50)
    if not keyword:
        raise ValueError("keyword is required")
    kw = keyword.upper()
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
    start = clean_date(start_date, "20200101")
    end = clean_date(end_date, _today_yyyymmdd())
    limit = clamp_int(limit, default=60, minimum=1, maximum=500)
    adjust = clean_text(adjust, max_len=8).lower()
    adjust_map = {"none": "0", "qfq": "1", "hfq": "2"}
    if adjust not in adjust_map:
        adjust = "qfq"
    fqt = adjust_map[adjust]
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": eastmoney_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": fqt,
        "beg": start,
        "end": end,
        "lmt": str(limit),
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
    limit = clamp_int(limit, default=12, minimum=1, maximum=40)
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
    limit = clamp_int(limit, default=30, minimum=1, maximum=100)
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


CNINFO_BASE_URL = "http://www.cninfo.com.cn"
CNINFO_STATIC_BASE_URL = "http://static.cninfo.com.cn"


def _to_cninfo_datetime(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # CNINFO announcementTime is Unix milliseconds in UTC+8 business time.
        return _dt.datetime.fromtimestamp(float(value) / 1000, tz=_dt.timezone.utc).astimezone(_dt.timezone(_dt.timedelta(hours=8))).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip().replace("T", " ")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text} 00:00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text):
        return text
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]} 00:00:00"
    return text[:32] or None


def _cninfo_detail_url(symbol: str | None, announcement_id: str | None, org_id: str | None, announcement_time: str | None) -> str | None:
    if not (symbol and announcement_id):
        return None
    url = f"{CNINFO_BASE_URL}/new/disclosure/detail?stockCode={symbol}&announcementId={announcement_id}"
    if org_id:
        url += f"&orgId={org_id}"
    if announcement_time:
        url += f"&announcementTime={quote(announcement_time)}"
    return url


def _cninfo_pdf_url(adjunct_url: Any) -> str | None:
    text = clean_text(adjunct_url, max_len=240)
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return text
    return f"{CNINFO_STATIC_BASE_URL}/{text.lstrip('/')}"


def _infer_cninfo_pdf_url(announcement_id: str | None, announcement_time: str | None) -> str | None:
    if not (announcement_id and announcement_time):
        return None
    date_part = announcement_time[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_part):
        return None
    return f"{CNINFO_STATIC_BASE_URL}/finalpage/{date_part}/{announcement_id}.PDF"


def normalize_announcement_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize CNINFO/AkShare announcement rows into stable public fields."""
    symbol = clean_text(record.get("secCode") or record.get("代码") or record.get("symbol"), max_len=16)
    if symbol:
        symbol = normalize_symbol(symbol)
    name = clean_text(record.get("secName") or record.get("简称") or record.get("name"), max_len=80) or None
    title = clean_text(record.get("announcementTitle") or record.get("公告标题") or record.get("title"), max_len=240) or None
    announcement_id = clean_text(record.get("announcementId") or record.get("announcement_id"), max_len=40) or None
    org_id = clean_text(record.get("orgId") or record.get("org_id"), max_len=40) or None
    published_at = _to_cninfo_datetime(record.get("announcementTime") or record.get("公告时间") or record.get("published_at"))
    detail_url = clean_text(record.get("公告链接") or record.get("detail_url"), max_len=500) or _cninfo_detail_url(symbol, announcement_id, org_id, published_at)
    pdf_url = _cninfo_pdf_url(record.get("adjunctUrl") or record.get("pdf_url")) or _infer_cninfo_pdf_url(announcement_id, published_at)
    file_type = clean_text(record.get("adjunctType") or record.get("file_type"), max_len=20) or ("PDF" if pdf_url else None)
    return {
        "symbol": symbol or None,
        "name": name,
        "title": title,
        "published_at": published_at,
        "announcement_id": announcement_id,
        "org_id": org_id,
        "detail_url": detail_url,
        "pdf_url": pdf_url,
        "pdf_size_kb": _clean_scalar(record.get("adjunctSize") or record.get("pdf_size_kb")),
        "file_type": file_type,
        "source": "cninfo" if (announcement_id or pdf_url or detail_url and "cninfo" in detail_url) else "eastmoney",
    }


def parse_announcement_detail_url(detail_url: str) -> dict[str, str | None]:
    parsed = urlparse(clean_text(detail_url, max_len=600))
    params = parse_qs(parsed.query)
    return {
        "symbol": (params.get("stockCode") or [None])[0],
        "announcement_id": (params.get("announcementId") or [None])[0],
        "org_id": (params.get("orgId") or [None])[0],
        "announcement_time": _to_cninfo_datetime((params.get("announcementTime") or [None])[0]),
    }


def _fetch_cninfo_announcements(symbol: str, keyword: str, category: str, start: str, end: str, limit: int) -> list[dict[str, Any]]:
    stock_item = symbol
    try:
        # CNINFO's search endpoint expects "code,orgId" for reliable company
        # filtering. Reuse AkShare's public-data mapping without exposing it.
        aks = require_akshare()
        get_stock_json = getattr(aks.stock_zh_a_disclosure_report_cninfo, "__globals__", {}).get("__get_stock_json")
        if get_stock_json:
            org_id = get_stock_json("沪深京").get(symbol)
            if org_id:
                stock_item = f"{symbol},{org_id}"
    except Exception:
        pass
    payload = {
        "pageNum": "1",
        "pageSize": str(limit),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_item,
        "searchkey": keyword,
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"{start[:4]}-{start[4:6]}-{start[6:]}~{end[:4]}-{end[4:6]}-{end[6:]}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    r = requests.post(
        f"{CNINFO_BASE_URL}/new/hisAnnouncement/query",
        data=payload,
        headers={"User-Agent": EASTMONEY_HEADERS["User-Agent"], "Referer": f"{CNINFO_BASE_URL}/new/commonUrl/pageOfSearch?url=disclosure/list/search"},
        timeout=20,
    )
    r.raise_for_status()
    payload_json = r.json()
    return list(payload_json.get("announcements") or [])[:limit]


@cached(ttl_seconds=3600)
def search_announcements(symbol: str, keyword: str = "", start_date: str | None = None, end_date: str | None = None, category: str = "", limit: int = 20) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    keyword = clean_text(keyword, max_len=120)
    category = clean_text(category, max_len=40)
    limit = clamp_int(limit, default=20, minimum=1, maximum=100)
    start = clean_date(start_date, (_dt.date.today() - _dt.timedelta(days=365)).strftime("%Y%m%d"))
    end = clean_date(end_date, _today_yyyymmdd())
    try:
        raw_records = _fetch_cninfo_announcements(code, keyword, category, start, end, limit)
        records = [normalize_announcement_record(row) for row in raw_records]
        source = "cninfo.hisAnnouncement.query"
    except Exception:
        aks = require_akshare()
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
        records = [normalize_announcement_record(row) for row in df_to_records(df, limit=limit)]
    return {
        "ok": True,
        "symbol": code,
        "source": source,
        "keyword": keyword,
        "category": category,
        "start_date": start,
        "end_date": end,
        "count": min(len(records), limit),
        "records": records[:limit],
        "fields": ["symbol", "name", "title", "published_at", "announcement_id", "org_id", "detail_url", "pdf_url", "pdf_size_kb", "file_type", "source"],
    }


def _sanitize_extracted_text(text: str, max_chars: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def assess_text_quality(text: str | None) -> dict[str, Any]:
    """Score extracted PDF text so garbled previews are not treated as reliable."""
    text = text or ""
    total = len(text)
    if total == 0:
        return {
            "quality": "empty",
            "length": 0,
            "printable_ratio": 0.0,
            "cjk_ratio": 0.0,
            "latin_digit_ratio": 0.0,
            "control_char_ratio": 0.0,
            "unknown_script_ratio": 0.0,
            "garbled_score": 1.0,
        }

    printable = 0
    cjk = 0
    latin_digit = 0
    control = 0
    whitespace_punct = 0
    unknown_script = 0
    for ch in text:
        code = ord(ch)
        if ch.isprintable() or ch in "\n\r\t":
            printable += 1
        if ch.isspace() or ch in "，。！？；：、,.!?;:()（）[]【】《》<>/\\-—_+*=%'\"“”‘’&%$#@|":
            whitespace_punct += 1
        elif "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            cjk += 1
        elif ch.isascii() and ch.isalnum():
            latin_digit += 1
        elif code < 32 or code == 127:
            control += 1
        else:
            unknown_script += 1

    content_chars = max(1, total - whitespace_punct)
    printable_ratio = printable / total
    cjk_ratio = cjk / content_chars
    latin_digit_ratio = latin_digit / content_chars
    control_char_ratio = control / total
    unknown_script_ratio = unknown_script / content_chars
    garbled_score = min(1.0, max(0.0, unknown_script_ratio * 1.35 + control_char_ratio * 2.0 + (1 - printable_ratio)))
    quality = "good"
    if total < 20:
        quality = "empty"
    elif garbled_score >= 0.35 or unknown_script_ratio >= 0.25 or printable_ratio < 0.9:
        quality = "poor"
    return {
        "quality": quality,
        "length": total,
        "printable_ratio": round(printable_ratio, 4),
        "cjk_ratio": round(cjk_ratio, 4),
        "latin_digit_ratio": round(latin_digit_ratio, 4),
        "control_char_ratio": round(control_char_ratio, 4),
        "unknown_script_ratio": round(unknown_script_ratio, 4),
        "garbled_score": round(garbled_score, 4),
    }


def should_try_ocr(text_mode: str, embedded_status: str) -> bool:
    mode = clean_text(text_mode, max_len=16).lower() or "auto"
    if mode == "ocr":
        return True
    if mode == "embedded":
        return False
    return embedded_status in {"poor_quality", "empty", "error", "unavailable"}


def ocr_result_to_text(result: Any) -> str:
    """Convert RapidOCR result tuples/lists into newline-delimited text."""
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = item[1]
            if text is not None:
                cleaned = clean_text(text, max_len=2000)
                if cleaned:
                    lines.append(cleaned)
    return "\n".join(lines)


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int, zoom: float = 2.0) -> list[bytes]:
    try:
        import fitz  # PyMuPDF
    except Exception as exc:
        raise RuntimeError(f"PyMuPDF unavailable: {type(exc).__name__}: {str(exc)[:120]}") from exc
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[bytes] = []
    matrix = fitz.Matrix(zoom, zoom)
    for page_index in range(min(max_pages, len(doc))):
        pix = doc[page_index].get_pixmap(matrix=matrix, alpha=False)
        images.append(pix.tobytes("png"))
    return images


def _extract_ocr_text(pdf_bytes: bytes, max_chars: int, max_pages: int) -> tuple[str | None, str, str | None, dict[str, Any] | None, int, str | None]:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except Exception as exc:
        return None, "unavailable", f"rapidocr_onnxruntime unavailable: {type(exc).__name__}: {str(exc)[:120]}", None, 0, None
    try:
        images = _render_pdf_pages(pdf_bytes, max_pages=max_pages)
        engine = RapidOCR()
        chunks: list[str] = []
        for image in images:
            result, _ = engine(image)
            page_text = ocr_result_to_text(result)
            if page_text:
                chunks.append(page_text)
            if sum(len(c) for c in chunks) >= max_chars:
                break
        text = _sanitize_extracted_text("\n".join(chunks), max_chars=max_chars)
        metrics = assess_text_quality(text)
        status = "ok" if metrics["quality"] == "good" else "poor_quality" if metrics["quality"] == "poor" else "empty"
        error = "OCR text appears garbled; use pdf_url as canonical source" if status == "poor_quality" else None
        return text if text else "", status, error, metrics, len(images), "rapidocr-onnxruntime"
    except Exception as exc:
        return None, "error", f"OCR extraction failed: {type(exc).__name__}: {str(exc)[:160]}", None, 0, "rapidocr-onnxruntime"


def _extract_pdf_text(pdf_bytes: bytes, max_chars: int, text_mode: str = "auto", max_pages: int = 3) -> tuple[str | None, str, str | None, dict[str, Any] | None, str, int, str | None]:
    text_mode = clean_text(text_mode, max_len=16).lower() or "auto"
    if text_mode not in {"auto", "embedded", "ocr"}:
        text_mode = "auto"
    max_pages = clamp_int(max_pages, default=3, minimum=1, maximum=20)
    if not pdf_bytes.startswith(b"%PDF"):
        return None, "error", "downloaded file is not a PDF", None, "none", 0, None
    embedded_text = None
    embedded_status = "skipped"
    embedded_error = None
    embedded_metrics = None
    if text_mode in {"auto", "embedded"}:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as exc:
            embedded_status = "unavailable"
            embedded_error = f"pypdf unavailable: {type(exc).__name__}: {str(exc)[:120]}"
        else:
            try:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                chunks = []
                for page in reader.pages[:max_pages]:
                    text = page.extract_text() or ""
                    if text:
                        chunks.append(text)
                    if sum(len(c) for c in chunks) >= max_chars:
                        break
                embedded_text = _sanitize_extracted_text("\n".join(chunks), max_chars=max_chars)
                embedded_metrics = assess_text_quality(embedded_text)
                embedded_status = "ok" if embedded_metrics["quality"] == "good" else "poor_quality" if embedded_metrics["quality"] == "poor" else "empty"
                embedded_error = "extracted text appears garbled; use pdf_url as canonical source" if embedded_status == "poor_quality" else None
            except Exception as exc:
                embedded_status = "error"
                embedded_error = f"PDF text extraction failed: {type(exc).__name__}: {str(exc)[:160]}"
    if text_mode == "embedded" or not should_try_ocr(text_mode, embedded_status):
        return embedded_text if embedded_text is not None else "", embedded_status, embedded_error, embedded_metrics, "embedded", max_pages if embedded_status not in {"unavailable", "error", "skipped"} else 0, None
    ocr_text, ocr_status, ocr_error, ocr_metrics, pages_processed, ocr_engine = _extract_ocr_text(pdf_bytes, max_chars=max_chars, max_pages=max_pages)
    if text_mode == "auto" and ocr_status in {"unavailable", "error", "empty"} and embedded_text is not None:
        fallback_error = ocr_error or embedded_error
        return embedded_text, embedded_status, fallback_error, embedded_metrics, "embedded", max_pages if embedded_status not in {"unavailable", "error", "skipped"} else 0, ocr_engine
    return ocr_text, ocr_status, ocr_error, ocr_metrics, "ocr", pages_processed, ocr_engine


@cached(ttl_seconds=6 * 3600)
def get_announcement_detail(symbol: str | None = None, announcement_id: str | None = None, detail_url: str | None = None, org_id: str | None = None, announcement_time: str | None = None, include_text: bool = False, max_chars: int = 4000, text_mode: str = "auto", max_pages: int = 3) -> dict[str, Any]:
    """Return normalized announcement metadata and optional PDF text preview."""
    include_text = parse_bool(include_text, default=False)
    max_chars = clamp_int(max_chars, default=4000, minimum=200, maximum=20000)
    text_mode = clean_text(text_mode, max_len=16).lower() or "auto"
    if text_mode not in {"auto", "embedded", "ocr"}:
        text_mode = "auto"
    max_pages = clamp_int(max_pages, default=3, minimum=1, maximum=20)
    parsed: dict[str, Any] = {}
    if detail_url:
        parsed = parse_announcement_detail_url(detail_url)
    code = normalize_symbol(symbol or parsed.get("symbol") or "")
    aid = clean_text(announcement_id or parsed.get("announcement_id"), max_len=40)
    oid = clean_text(org_id or parsed.get("org_id"), max_len=40) or None
    atime = _to_cninfo_datetime(announcement_time or parsed.get("announcement_time"))
    if not aid:
        raise ValueError("announcement_id or detail_url is required")
    announcement = normalize_announcement_record({
        "secCode": code,
        "orgId": oid,
        "announcementId": aid,
        "announcementTime": atime,
        "公告链接": detail_url,
    })
    text = None
    text_status = "skipped"
    text_quality = "not_requested"
    text_quality_metrics = None
    text_error = None
    content_length = None
    text_extraction_method = "none"
    pages_processed = 0
    ocr_engine = None
    if include_text and announcement.get("pdf_url"):
        r = requests.get(str(announcement["pdf_url"]), headers=EASTMONEY_HEADERS, timeout=30)
        r.raise_for_status()
        content_length = len(r.content)
        text, text_status, text_error, text_quality_metrics, text_extraction_method, pages_processed, ocr_engine = _extract_pdf_text(r.content, max_chars=max_chars, text_mode=text_mode, max_pages=max_pages)
        text_quality = text_quality_metrics.get("quality") if text_quality_metrics else "unavailable"
    return {
        "ok": True,
        "symbol": code,
        "source": "cninfo",
        "announcement": announcement,
        "text": text,
        "text_status": text_status,
        "text_quality": text_quality,
        "text_quality_metrics": text_quality_metrics,
        "text_extraction_method": text_extraction_method,
        "pages_processed": pages_processed,
        "ocr_engine": ocr_engine,
        "text_mode": text_mode,
        "text_error": text_error,
        "content_length": content_length,
        "warnings": [
            "For research and education only; not investment advice.",
            "Announcement text extraction is best-effort; use the PDF URL as canonical source.",
        ],
    }


@cached(ttl_seconds=6 * 3600)
def search_research_reports(symbol: str, limit: int = 20) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    limit = clamp_int(limit, default=20, minimum=1, maximum=100)
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
    highs = [float(r.get("high") or r["close"]) for r in records]
    lows = [float(r.get("low") or r["close"]) for r in records]
    volumes = [float(r.get("volume") or 0) for r in records]
    turnovers = [float(r.get("turnover") or 0) for r in records]
    latest = records[-1]
    high_value = max(highs)
    low_value = min(lows)
    high_idx = highs.index(high_value)
    low_idx = lows.index(low_value)
    max_drawdown = 0.0
    peak = closes[0]
    for close in closes:
        peak = max(peak, close)
        if peak:
            max_drawdown = min(max_drawdown, close / peak - 1)
    stats = {
        "period_start": records[0].get("date"),
        "period_end": latest.get("date"),
        "latest_date": latest.get("date"),
        "latest_close": latest.get("close"),
        "period_high": high_value,
        "period_high_date": records[high_idx].get("date"),
        "period_low": low_value,
        "period_low_date": records[low_idx].get("date"),
        "return_pct": round((closes[-1] / closes[0] - 1) * 100, 4) if closes[0] else None,
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "avg_volume": round(sum(volumes) / len(volumes), 4) if volumes else None,
        "avg_turnover": round(sum(turnovers) / len(turnovers), 4) if turnovers else None,
    }
    for n in (5, 10, 20, 60, 120, 250):
        if len(closes) >= n:
            window = closes[-n:]
            ma = round(sum(window) / n, 4)
            stats[f"ma{n}"] = ma
            stats[f"latest_vs_ma{n}_pct"] = round((closes[-1] / ma - 1) * 100, 4) if ma else None
            stats[f"return_{n}d_pct"] = round((closes[-1] / closes[-n] - 1) * 100, 4) if closes[-n] else None
    return stats


def _safe_section(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = fn()
        if isinstance(result, dict):
            return result
        return {"ok": False, "section": name, "error": "InvalidResult", "message": "section did not return a dict"}
    except Exception as exc:
        return {"ok": False, "section": name, "error": type(exc).__name__, "message": str(exc)[:240]}


def _source_ledger(sections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for name, section in sections.items():
        ok_value = section.get("ok")
        entry = {
            "section": name,
            "ok": ok_value,
            "status": "ok" if ok_value is True else "skipped" if ok_value is None else "error",
            "source": section.get("source"),
        }
        if "start_date" in section:
            entry["start_date"] = section.get("start_date")
        if "end_date" in section:
            entry["end_date"] = section.get("end_date")
        if "count" in section:
            entry["count"] = section.get("count")
        if section.get("ok") is False:
            entry["error"] = section.get("error")
            entry["message"] = section.get("message")
        ledger.append(entry)
    return ledger


def _section_status(sections: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: {k: section.get(k) for k in ("ok", "source", "error", "message") if k in section} for name, section in sections.items()}


@cached(ttl_seconds=3600)
def get_company_snapshot(symbol: str, history_days: int = 60, announcement_limit: int = 5) -> dict[str, Any]:
    """Return an agent-friendly research pack for one A-share company."""
    code = normalize_symbol(symbol)
    history_days = clamp_int(history_days, default=60, minimum=5, maximum=250)
    announcement_limit = clamp_int(announcement_limit, default=5, minimum=1, maximum=20)
    quote = _safe_section("quote", lambda: get_realtime_quote(code))
    profile = _safe_section("profile", lambda: get_stock_profile(code))
    history = _safe_section("history", lambda: get_daily_history(code, limit=history_days))
    financial = _safe_section("financial", lambda: get_financial_summary(code))
    business = _safe_section("business", lambda: get_business_composition(code, limit=10))
    announcements = _safe_section("announcements", lambda: search_announcements(code, limit=announcement_limit))
    sections = {
        "quote": quote,
        "profile": profile,
        "history": history,
        "financial": financial,
        "business": business,
        "announcements": announcements,
    }
    warnings = [
        "For research only; not investment advice.",
        "Public endpoints can be delayed or unavailable; verify important figures against official filings.",
        "Price history adjustment mode defaults to qfq when using get_daily_history directly.",
    ]
    for section_name, section in sections.items():
        if section.get("ok") is False:
            warnings.append(f"{section_name} unavailable: {section.get('error')}: {section.get('message')}")
    q = quote.get("quote", {}) if quote.get("ok") else {}
    p = profile.get("profile", {}) if profile.get("ok") else {}
    return {
        "ok": any(section.get("ok") is True for section in sections.values()),
        "partial": any(section.get("ok") is False for section in sections.values()),
        "symbol": code,
        "name": q.get("name") or p.get("股票简称"),
        "market": market_prefix(code),
        "sources": {name: section.get("source") for name, section in sections.items() if section.get("source")},
        "quote": q or None,
        "profile": p or None,
        "price_history_stats": _history_stats(history.get("records", [])) if history.get("ok") else {},
        "financial_summary": financial.get("key_metrics") if financial.get("ok") else {},
        "business_composition_sample": business.get("records", [])[:10] if business.get("ok") else [],
        "recent_announcements": announcements.get("records", [])[:announcement_limit] if announcements.get("ok") else [],
        "section_status": _section_status(sections),
        "source_ledger": _source_ledger(sections),
        "warnings": warnings,
    }


@cached(ttl_seconds=3600)
def get_research_pack(symbol: str, history_days: int = 120, announcement_limit: int = 10, include_reports: bool = False, report_limit: int = 5) -> dict[str, Any]:
    """Build a generic A-share data pack for agent-side company analysis.

    This tool deliberately returns structured data only. It does not write
    reports, create recommendations, or call external workflows.
    """
    code = normalize_symbol(symbol)
    history_days = clamp_int(history_days, default=120, minimum=20, maximum=500)
    announcement_limit = clamp_int(announcement_limit, default=10, minimum=1, maximum=50)
    report_limit = clamp_int(report_limit, default=5, minimum=1, maximum=20)
    include_reports = parse_bool(include_reports, default=False)
    quote = _safe_section("quote", lambda: get_realtime_quote(code))
    profile = _safe_section("profile", lambda: get_stock_profile(code))
    history = _safe_section("history", lambda: get_daily_history(code, limit=history_days))
    financial_raw = _safe_section("financial_indicators", lambda: get_financial_indicators(code, start_year="2023", limit=12))
    financial_summary = _safe_section("financial_summary", lambda: get_financial_summary(code, start_year="2023"))
    business = _safe_section("business_composition", lambda: get_business_composition(code, limit=20))
    announcements = _safe_section("announcements", lambda: search_announcements(code, limit=announcement_limit))
    reports = _safe_section("research_reports", lambda: search_research_reports(code, limit=report_limit)) if include_reports else {"ok": None, "source": None, "records": []}
    sections = {
        "quote": quote,
        "profile": profile,
        "history": history,
        "financial_indicators": financial_raw,
        "financial_summary": financial_summary,
        "business_composition": business,
        "announcements": announcements,
        "research_reports": reports,
    }
    q = quote.get("quote", {}) if quote.get("ok") else {}
    p = profile.get("profile", {}) if profile.get("ok") else {}
    history_records = history.get("records", []) if history.get("ok") else []
    warnings = [
        "For research and education only; not investment advice.",
        "Verify important figures against official filings before publication or decision-making.",
        "Broker research, when included, is background material and not canonical evidence.",
    ]
    for section_name, section in sections.items():
        if section.get("ok") is False:
            warnings.append(f"{section_name} unavailable: {section.get('error')}: {section.get('message')}")
    return {
        "ok": any(section.get("ok") is True for section in sections.values()),
        "partial": any(section.get("ok") is False for section in sections.values()),
        "symbol": code,
        "name": q.get("name") or p.get("股票简称"),
        "market": market_prefix(code),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "input": {
            "history_days": history_days,
            "announcement_limit": announcement_limit,
            "include_reports": include_reports,
            "report_limit": report_limit if include_reports else 0,
        },
        "company": {
            "profile": p or None,
            "quote": q or None,
            "valuation": {
                "total_market_cap": q.get("total_market_cap"),
                "float_market_cap": q.get("float_market_cap"),
                "pe_ttm": q.get("pe_ttm"),
                "pb": q.get("pb"),
            } if q else {},
        },
        "price": {
            "stats": _history_stats(history_records),
            "records": history_records,
        },
        "financials": {
            "summary": financial_summary.get("key_metrics") if financial_summary.get("ok") else {},
            "raw_records": financial_raw.get("records", []) if financial_raw.get("ok") else [],
            "columns": financial_raw.get("columns", []) if financial_raw.get("ok") else [],
        },
        "business": {
            "composition": business.get("records", []) if business.get("ok") else [],
        },
        "events": {
            "announcements": announcements.get("records", []) if announcements.get("ok") else [],
            "research_reports": reports.get("records", []) if reports.get("ok") else [],
        },
        "source_ledger": _source_ledger(sections),
        "section_status": _section_status(sections),
        "warnings": warnings,
    }



def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except Exception:
        return None


def _a_share_spot_records(limit: int = 6000) -> dict[str, Any]:
    """Return A-share spot records, preferring AkShare with Eastmoney fallback."""
    limit = clamp_int(limit, default=6000, minimum=1, maximum=6000)
    try:
        aks = require_akshare()
        df = aks.stock_zh_a_spot_em()
        return {"ok": True, "source": "akshare.stock_zh_a_spot_em/eastmoney", "records": df_to_records(df, limit=limit)}
    except Exception as ak_exc:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": str(limit),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81",
            "fields": "f12,f14,f2,f3,f8,f9,f20,f21,f23,f100,f13",
        }
        try:
            r = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=30)
            r.raise_for_status()
            rows = (((r.json() or {}).get("data") or {}).get("diff") or [])[:limit]
        except Exception as em_exc:
            return {"ok": False, "source": "a_share_spot_unavailable", "records": [], "error": type(em_exc).__name__, "message": str(em_exc)[:200], "akshare_error": type(ak_exc).__name__}
        records = []
        for row in rows:
            records.append({
                "代码": row.get("f12"),
                "名称": row.get("f14"),
                "最新价": row.get("f2"),
                "涨跌幅": row.get("f3"),
                "换手率": row.get("f8"),
                "市盈率-动态": row.get("f9"),
                "总市值": row.get("f20"),
                "流通市值": row.get("f21"),
                "市净率": row.get("f23"),
                "行业": row.get("f100"),
            })
        return {"ok": True, "source": f"eastmoney.push2.clist fallback after {type(ak_exc).__name__}", "records": records}


def _spot_record_to_peer(record: dict[str, Any]) -> dict[str, Any]:
    code = normalize_symbol(str(record.get("代码") or record.get("symbol") or record.get("股票代码") or ""))
    return {
        "symbol": code,
        "name": record.get("名称") or record.get("股票简称") or record.get("name"),
        "market": market_prefix(code),
        "industry": record.get("行业") or record.get("所处行业"),
        "price": _safe_float(record.get("最新价")),
        "change_pct": _safe_float(record.get("涨跌幅")),
        "turnover_rate_pct": _safe_float(record.get("换手率")),
        "total_market_cap": _safe_float(record.get("总市值")),
        "float_market_cap": _safe_float(record.get("流通市值")),
        "pe_ttm": _safe_float(record.get("市盈率-动态") or record.get("市盈率TTM") or record.get("市盈率")),
        "pb": _safe_float(record.get("市净率")),
    }


def _percentile_rank(values: list[float], target: float | None) -> float | None:
    if target is None:
        return None
    clean = sorted(v for v in values if v is not None and not math.isnan(v))
    if not clean:
        return None
    below_or_equal = sum(1 for v in clean if v <= target)
    return round(below_or_equal / len(clean) * 100, 4)


@cached(ttl_seconds=1800)
def get_industry_peers(symbol: str, limit: int = 30) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    limit = clamp_int(limit, default=30, minimum=1, maximum=100)
    target_quote = get_realtime_quote(code)
    industry = ((target_quote.get("quote") or {}).get("industry"))
    spot = _a_share_spot_records()
    if spot.get("ok") is False:
        q = target_quote.get("quote") or {}
        target = {
            "symbol": code,
            "name": q.get("name"),
            "market": market_prefix(code),
            "industry": industry,
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "turnover_rate_pct": q.get("turnover_rate_pct"),
            "total_market_cap": q.get("total_market_cap"),
            "float_market_cap": q.get("float_market_cap"),
            "pe_ttm": q.get("pe_ttm"),
            "pb": q.get("pb"),
        }
        return {
            "ok": True,
            "partial": True,
            "symbol": code,
            "industry": industry,
            "source": spot.get("source"),
            "count": 1,
            "records": [target],
            "warnings": ["For research and education only; not investment advice.", f"Peer universe unavailable: {spot.get('error')}: {spot.get('message')}"]
        }
    peers = []
    for record in spot.get("records", []):
        try:
            peer = _spot_record_to_peer(record)
        except Exception:
            continue
        if industry and peer.get("industry") != industry:
            continue
        peers.append(peer)
    peers = sorted(peers, key=lambda r: (r.get("total_market_cap") is None, -(r.get("total_market_cap") or 0)))[:limit]
    return {
        "ok": True,
        "symbol": code,
        "industry": industry,
        "source": spot.get("source"),
        "count": len(peers),
        "records": peers,
        "warnings": ["For research and education only; not investment advice.", "Peer lists are based on public industry labels and may differ across data vendors."],
    }


@cached(ttl_seconds=1800)
def get_peer_comparison(symbol: str, limit: int = 30) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    peers_result = get_industry_peers(code, limit=limit)
    peers = peers_result.get("records", [])
    target = next((p for p in peers if p.get("symbol") == code), None)
    if target is None:
        q = (get_realtime_quote(code).get("quote") or {})
        target = {
            "symbol": code,
            "name": q.get("name"),
            "market": market_prefix(code),
            "industry": peers_result.get("industry"),
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "total_market_cap": q.get("total_market_cap"),
            "float_market_cap": q.get("float_market_cap"),
            "pe_ttm": q.get("pe_ttm"),
            "pb": q.get("pb"),
        }
    metrics = ["total_market_cap", "float_market_cap", "pe_ttm", "pb", "change_pct", "turnover_rate_pct"]
    comparison = {}
    for metric in metrics:
        values = [_safe_float(p.get(metric)) for p in peers]
        target_value = _safe_float(target.get(metric))
        comparison[metric] = {
            "target_value": target_value,
            "percentile_rank": _percentile_rank([v for v in values if v is not None], target_value),
            "peer_median": round(pd.Series([v for v in values if v is not None]).median(), 4) if any(v is not None for v in values) else None,
        }
    return {
        "ok": True,
        "symbol": code,
        "industry": peers_result.get("industry"),
        "source": peers_result.get("source"),
        "target": target,
        "peer_count": len(peers),
        "comparison": comparison,
        "peers": peers,
        "warnings": ["For research and education only; not investment advice.", "Percentiles are simple ranks within the returned peer set, not valuation conclusions."],
    }


INDEX_SECID_MAP = {
    "000001": "1.000001",
    "399001": "0.399001",
    "399006": "0.399006",
    "000300": "1.000300",
    "000905": "1.000905",
    "000852": "1.000852",
}

def _index_secid(symbol: str) -> str:
    code = normalize_symbol(symbol)
    return INDEX_SECID_MAP.get(code, f"1.{code}" if code.startswith("0") else f"0.{code}")


@cached(ttl_seconds=60)
def get_index_snapshot(symbol: str = "000001") -> dict[str, Any]:
    code = normalize_symbol(symbol)
    fields = "f12,f14,f2,f3,f4,f5,f6,f7,f15,f16,f17,f18,f124"
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt": "2", "secids": _index_secid(code), "fields": fields}
    r = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=20)
    r.raise_for_status()
    diff = (((r.json() or {}).get("data") or {}).get("diff") or [])
    if not diff:
        raise RuntimeError(f"no index data returned for {code}")
    q = diff[0]
    return {
        "ok": True,
        "symbol": code,
        "source": "eastmoney.push2.ulist/index",
        "index": {
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
            "quote_timestamp": q.get("f124"),
        },
        "warnings": ["For research and education only; not investment advice."],
    }


@cached(ttl_seconds=1800)
def get_sector_snapshot(sector_type: str = "industry", limit: int = 30) -> dict[str, Any]:
    sector_type = clean_text(sector_type, max_len=16).lower() or "industry"
    limit = clamp_int(limit, default=30, minimum=1, maximum=100)
    try:
        aks = require_akshare()
        if sector_type == "concept":
            df = aks.stock_board_concept_name_em()
            source = "akshare.stock_board_concept_name_em/eastmoney"
        else:
            df = aks.stock_board_industry_name_em()
            source = "akshare.stock_board_industry_name_em/eastmoney"
        return {"ok": True, "sector_type": sector_type, "source": source, "count": min(len(df), limit), "records": df_to_records(df, limit=limit), "warnings": ["For research and education only; not investment advice."]}
    except Exception as exc:
        return {"ok": True, "partial": True, "sector_type": sector_type, "source": "sector_snapshot_unavailable", "count": 0, "records": [], "warnings": [f"Sector endpoint unavailable: {type(exc).__name__}: {str(exc)[:160]}"]}


@cached(ttl_seconds=1800)
def get_sector_components(sector_name: str, sector_type: str = "industry", limit: int = 50) -> dict[str, Any]:
    sector_name = clean_text(sector_name, max_len=80)
    if not sector_name:
        raise ValueError("sector_name is required")
    sector_type = clean_text(sector_type, max_len=16).lower() or "industry"
    limit = clamp_int(limit, default=50, minimum=1, maximum=200)
    try:
        aks = require_akshare()
        if sector_type == "concept":
            df = aks.stock_board_concept_cons_em(symbol=sector_name)
            source = "akshare.stock_board_concept_cons_em/eastmoney"
        else:
            df = aks.stock_board_industry_cons_em(symbol=sector_name)
            source = "akshare.stock_board_industry_cons_em/eastmoney"
        return {"ok": True, "sector_type": sector_type, "sector_name": sector_name, "source": source, "count": min(len(df), limit), "records": df_to_records(df, limit=limit), "warnings": ["For research and education only; not investment advice."]}
    except Exception as exc:
        return {"ok": True, "partial": True, "sector_type": sector_type, "sector_name": sector_name, "source": "sector_components_unavailable", "count": 0, "records": [], "warnings": [f"Sector components endpoint unavailable: {type(exc).__name__}: {str(exc)[:160]}"]}

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
