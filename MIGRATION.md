# Migration Guide

## v0.x to v1.x

No tool names were removed. Existing clients that use v0.7.x tools should continue to work.

Notable additions:

- `batch_get_quotes` and `batch_company_snapshot` return `partial=true` plus `errors` when some symbols fail.
- New v1-style helper outputs may include `source_ledger`, `data_quality`, and standardized `warnings`. Clients should tolerate additional response fields.
- Cache operations are exposed through `get_cache_status` and `clear_cache`.

Compatibility policy from v1.0.0:

- Patch releases: bug fixes, no intentional field removals.
- Minor releases: additive tools/arguments/fields.
- Major releases: may contain breaking changes with this migration guide updated.
