# Changelog

## v1.1.0

Cumulative release that completes the v0.8 → v1.1 stabilization roadmap.

### Data quality / stability

- Add `with_quality_metadata()` helper for consistent `source_ledger`, `data_quality`, freshness, partial state, and research-only disclaimer metadata.
- Batch/composite tools preserve partial failures instead of failing whole calls.
- `screen_stocks` now reports unavailable upstream universes as `partial=true` instead of a hard failure.

### Batch / agent workflow tools

- Add `batch_get_quotes`.
- Add `batch_company_snapshot`.
- Add `compare_companies`.
- Add `screen_stocks`.
- Add `get_market_overview`.

### Stable API / documentation

- Declare v1 compatibility policy in README and migration guide.
- Add `CHANGELOG.md` and `MIGRATION.md`.
- Expand examples and smoke coverage.

### v1.1 data helpers

- Add `get_financial_trends` for compact financial trend summaries.
- Add `classify_announcements` for keyword-based announcement classification.
- Add `get_cache_status` and `clear_cache` for cache operations.

## v0.7.1

- Add daily history fallback to AkShare/Sina when Eastmoney kline disconnects.

## v0.7.0 and earlier

- Add announcement PDF layout extraction, financial event tools, index/sector tools, peer comparison, announcement detail/PDF/OCR, research packs, and public-ready MCP packaging.
