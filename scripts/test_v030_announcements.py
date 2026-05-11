from __future__ import annotations

import json

from a_share_mcp import data


def test_normalize_cninfo_announcement_record() -> None:
    raw = {
        "secCode": "603259",
        "secName": "药明康德",
        "orgId": "9900035584",
        "announcementId": "1225278835",
        "announcementTitle": "H股公告",
        "announcementTime": 1778083200000,
        "adjunctUrl": "finalpage/2026-05-07/1225278835.PDF",
        "adjunctSize": 130,
        "adjunctType": "PDF",
    }

    normalized = data.normalize_announcement_record(raw)

    assert normalized == {
        "symbol": "603259",
        "name": "药明康德",
        "title": "H股公告",
        "published_at": "2026-05-07 00:00:00",
        "announcement_id": "1225278835",
        "org_id": "9900035584",
        "detail_url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=603259&announcementId=1225278835&orgId=9900035584&announcementTime=2026-05-07%2000%3A00%3A00",
        "pdf_url": "http://static.cninfo.com.cn/finalpage/2026-05-07/1225278835.PDF",
        "pdf_size_kb": 130,
        "file_type": "PDF",
        "source": "cninfo",
    }


def test_parse_announcement_detail_url() -> None:
    url = "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=603259&announcementId=1225278835&orgId=9900035584&announcementTime=2026-05-07%2000:00:00"

    parsed = data.parse_announcement_detail_url(url)

    assert parsed["symbol"] == "603259"
    assert parsed["announcement_id"] == "1225278835"
    assert parsed["org_id"] == "9900035584"
    assert parsed["announcement_time"] == "2026-05-07 00:00:00"


def test_get_announcement_detail_from_url_without_text() -> None:
    url = "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=603259&announcementId=1225278835&orgId=9900035584&announcementTime=2026-05-07%2000:00:00"

    detail = data.get_announcement_detail(detail_url=url, include_text=False)

    assert detail["ok"] is True
    assert detail["announcement"]["announcement_id"] == "1225278835"
    assert detail["announcement"]["pdf_url"] == "http://static.cninfo.com.cn/finalpage/2026-05-07/1225278835.PDF"
    assert detail["text"] is None
    assert detail["text_status"] == "skipped"


def main() -> int:
    tests = [
        test_normalize_cninfo_announcement_record,
        test_parse_announcement_detail_url,
        test_get_announcement_detail_from_url_without_text,
    ]
    for test in tests:
        test()
    print(json.dumps({"ok": True, "tests": len(tests)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
