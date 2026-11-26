# Changelog

## 1.0.0 - 2026-11-17

Initial release.

* WordPress comments audit over a CSV export from
  `wp comment list --format=csv` (plus an optional post_date
  column): comments stuck unapproved past N days, spam-pattern
  comments (excessive links, known spam phrases, keyword
  stuffing, gibberish bursts), duplicate comments from the
  same author, comments on very old posts, comments from
  authors with no approved comment ever, pingbacks and
  trackbacks mixed in with real comments, and bad data such
  as missing authors or emails, invalid or future dates,
  duplicate comment ids, and malformed rows.
* Spam signals flagged as errors: known spam phrases and
  comments with more links than --max-links (default 3).
  Duplicate comments and duplicate comment ids are errors;
  the duplicate id row is skipped so one comment cannot
  count twice.
* Stale pending comments flagged as warnings after
  --max-age-days (default 30). Authors with no approved
  comment in the whole export get one warning each.
  Comments on posts published more than 365 days before the
  comment are warnings when the post_date column is present.
* Data errors reported and skipped, never a crash: missing
  authors and emails, invalid emails, missing comment ids,
  malformed rows, invalid and future dates, unknown statuses,
  empty and thin comments, pingbacks and trackbacks.
* Dates accepted as YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, ISO
  datetime, YYYY/MM/DD, or DD/MM/YYYY; header aliases cover
  the wp comment list field names; a UTF-8 BOM header is
  handled.
* A per-post table counts comments, approved, pending, and
  spam per post, and a per-author table counts comments and
  approved comments per author. The summary reports comments,
  approved, pending, spam, trash, findings, errors, and
  warnings.
* Text and --json output, --out file output, and a --check CI
  gate that exits 1 on errors (and on warnings with --strict).
  --as-of pins the reference date, --max-links,
  --max-age-days, and --min-words tune the thresholds.
* Zero dependencies, Python 3.10 or newer.
