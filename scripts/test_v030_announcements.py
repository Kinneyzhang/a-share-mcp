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
    assert detail["text_quality"] == "not_requested"
    assert detail["text_quality_metrics"] is None
    assert detail["text_extraction_method"] == "none"
    assert detail["pages_processed"] == 0


def test_text_mode_ocr_decision_rules() -> None:
    assert data.should_try_ocr("auto", "poor_quality") is True
    assert data.should_try_ocr("auto", "empty") is True
    assert data.should_try_ocr("auto", "ok") is False
    assert data.should_try_ocr("embedded", "poor_quality") is False
    assert data.should_try_ocr("ocr", "ok") is True


def test_ocr_result_to_text() -> None:
    result = [
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "贵州茅台股份有限公司", 0.98],
        [[[0, 2], [1, 2], [1, 3], [0, 3]], "2025 年年度报告", 0.96],
    ]

    text = data.ocr_result_to_text(result)

    assert text == "贵州茅台股份有限公司\n2025 年年度报告"


def test_text_quality_good_for_normal_chinese_text() -> None:
    text = "贵州茅台股份有限公司 2025 年年度报告。本公告内容真实、准确、完整。营业收入和净利润保持稳定。"

    metrics = data.assess_text_quality(text)

    assert metrics["quality"] == "good"
    assert metrics["cjk_ratio"] > 0.4
    assert metrics["garbled_score"] < 0.35


def test_text_quality_poor_for_garbled_pdf_text() -> None:
    text = "FF301\n∉ ⊈ಊṉọᄅḸі ٺ୍ ᄅ ರ ⊯Ⅲ ࢌ\nඳ଀Ẁ ඳ ರ௹ ୍ ᄅ ರ\nЧṉọ\n ٳٺܢܢ⦁ )෮ഈ൧ 䩏"

    metrics = data.assess_text_quality(text)

    assert metrics["quality"] == "poor"
    assert metrics["garbled_score"] >= 0.35


def main() -> int:
    tests = [
        test_normalize_cninfo_announcement_record,
        test_parse_announcement_detail_url,
        test_get_announcement_detail_from_url_without_text,
        test_text_mode_ocr_decision_rules,
        test_ocr_result_to_text,
        test_text_quality_good_for_normal_chinese_text,
        test_text_quality_poor_for_garbled_pdf_text,
    ]
    for test in tests:
        test()
    print(json.dumps({"ok": True, "tests": len(tests)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
