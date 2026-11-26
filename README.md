# wp-comment-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/wp-comment-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/wp-comment-doctor/issues)

A zero-dependency Python CLI that audits a WordPress comments
CSV export for the comments that most often signal spam,
neglect, or a broken moderation queue: comments stuck
unapproved for weeks, spam-pattern comments (excessive links,
known spam phrases, keyword stuffing, gibberish bursts),
duplicate comments from the same author, comments on very old
posts, comments from authors who have never had one approved,
pingbacks and trackbacks mixed in with real comments, and bad
data such as missing authors or emails, invalid or future
dates, duplicate comment ids, and malformed rows.

A WordPress site with comments left unmoderated for months is
a spam magnet: search engines index the junk, real readers stop
commenting, and a single unapproved thread can hide a genuine
question from a paying customer. WP-CLI lists comments but does
not score them, and the moderation screen shows one page at a
time. This tool is the offline audit of the exported list.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install wp-comment-doctor
```

Or run it straight from the source checkout:

```bash
python3 wp_comment_doctor.py examples/comments.csv --as-of 2026-11-17
```

## Input format

A CSV export with a header row, as produced by
`wp comment list --format=csv`, plus an optional `post_date`
column when the export carries the post publish date. Columns
used: `comment_id`, `post_id`, `post_title`, `author`,
`author_email`, `author_url`, `date`, `status`,
`comment_type`, `content`, and `post_date`. The aliases
`comment_ID` and `id` work for the comment id, `comment_author`
for the author, `comment_author_email` for the email,
`comment_date` and `comment_date_gmt` for the date,
`comment_approved` for the status, and `comment_content` for
the content. A UTF-8 BOM header is handled. Dates are accepted
as YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, ISO datetime, YYYY/MM/DD,
or DD/MM/YYYY. Status values are `1` or `approved`, `0` or
`pending` (also `hold` and `unapproved`), `spam`, and `trash`.

```csv
comment_id,post_id,post_title,author,author_email,author_url,date,status,comment_type,content,post_date
101,12,How to speed up WordPress,Sara Ahmed,sara@example.com,https://sara.example.com,2026-11-15 09:00:00,1,comment,"Great guide, the caching section saved me a lot of time.",2026-10-01
102,12,How to speed up WordPress,Tom Reed,tom@example.com,,2026-09-01 10:00:00,0,comment,"I tried the steps but my site still loads slowly, any advice?",2026-10-01
103,15,Best hosting for WooCommerce,Spammer One,deals@example.com,,2026-11-10 11:00:00,0,comment,"Buy cheap viagra now, limited time offer, act now for guaranteed income!",2026-11-01
```

Export it with WP-CLI:

```bash
wp comment list --format=csv --fields=comment_ID,comment_post_ID,comment_author,comment_author_email,comment_author_url,comment_date,comment_approved,comment_type,comment_content > comments.csv
```

## What it checks

Every finding includes a short suggested `action` so a
moderator can work through the queue without guessing the
next step.

Errors, the ones that are live spam or break the audit:

* `spam-phrase`: the comment contains a known spam phrase
  (buy cheap, viagra, casino, make money fast, free followers,
  and the rest of the built-in list).
* `too-many-links`: the comment contains more links than
  `--max-links` (default 3).
* `duplicate-comment`: the same author posted the same content
  before. Matching is case-insensitive and ignores extra
  whitespace, so a copy-paste resubmit is caught.
* `duplicate-comment-id`: a comment id that already appears in
  the export. The duplicate row is skipped, so one comment
  cannot count twice.
* `missing-comment-id`: a row with no comment id. The row is
  skipped, because it cannot be tracked.
* `missing-author`: a comment with no author, so it cannot be
  attributed or replied to.
* `missing-email`: a comment with no author email, so the
  author cannot be contacted.
* `invalid-email`: an email that is missing or not a valid
  email address.
* `malformed-row`: a row with the wrong number of fields. The
  row is skipped and reported, never a crash.

Warnings, comments worth following up:

* `stale-pending`: a comment unapproved for more than
  `--max-age-days` (default 30). Action: "Approve or trash it."
* `no-approved-ever`: an author with no approved comment in
  the whole export. One finding per author, not one per
  comment, so a chronic non-approved author does not flood
  the report. Action: "Review the author's comments before approving."
* `old-post-comment`: a comment on a post published more than
  365 days before the comment. Needs the `post_date` column;
  without it the check is skipped and a note line says so.
  Action: "Review and approve, close, or trash it."
* `pingback-mixed`: a pingback or trackback sitting in with
  the real comments.
* `keyword-stuffing`: one word of four or more letters appears
  at least five times and makes up at least a quarter of the
  long words in the comment.
* `gibberish-content`: more than 40% non-ASCII letters, a run
  of the same character repeated 6 or more times, or a run of
  10 or more consonants.
* `empty-content`: a comment with no content at all.
* `thin-comment`: a comment with fewer words than
  `--min-words` (default 3).
* `invalid-date`: a comment date that is not a recognised date.
* `future-date`: a comment date in the future.
* `unknown-status`: a status that is not a recognised
  WordPress comment status.

## Usage

```bash
python3 wp_comment_doctor.py examples/comments.csv --as-of 2026-11-17
```

Captured output:

```
WARNING [stale-pending] #102: comment has been unapproved for 77 days, above the maximum of 30
ERROR [spam-phrase] #103: comment contains the known spam phrase 'buy cheap'
ERROR [too-many-links] #104: comment contains 4 links, above the maximum of 3
ERROR [duplicate-comment] #105: same author and same content as an earlier comment, so this looks like a duplicate submission
ERROR [duplicate-comment-id] #101: comment id already appears in this export, so this duplicate row was skipped
ERROR [missing-author] #106: comment has no author, so it cannot be attributed or replied to
ERROR [missing-email] #107: comment has no author email, so the author cannot be contacted
ERROR [invalid-email] #108: email 'not-an-email' is missing or not a valid email address
WARNING [invalid-date] #109: date 'not-a-date' is not a recognised date
WARNING [future-date] #110: date 2027-01-01 is in the future
WARNING [old-post-comment] #111: comment is on a post published 2496 days before the comment
WARNING [pingback-mixed] #112: this is a pingback, not a real comment, and it is mixed in with the comments
WARNING [empty-content] #113: comment has no content
WARNING [thin-comment] #114: comment has only 1 word(s), below the minimum of 3
WARNING [keyword-stuffing] #115: the word 'great' is repeated so often the comment reads as keyword stuffing
WARNING [gibberish-content] #116: comment looks like gibberish: contains a run of the same character repeated 6 or more times
WARNING [pingback-mixed] #118: this is a trackback, not a real comment, and it is mixed in with the comments
ERROR [malformed-row] row 22: row has 9 fields but the header has 11, so the row was skipped
WARNING [no-approved-ever] Lonely Poster: author has no approved comment in this export (1 comment(s), all unapproved, spam, or trash)
WARNING [no-approved-ever] Spammer One: author has no approved comment in this export (1 comment(s), all unapproved, spam, or trash)
WARNING [no-approved-ever] Tom Reed: author has no approved comment in this export (1 comment(s), all unapproved, spam, or trash)

Per post:
Best hosting for WooCommerce (#15): 5 comment(s), 4 approved, 1 pending, 0 spam
Hello world! (#20): 1 comment(s), 1 approved, 0 pending, 0 spam
How to speed up WordPress (#12): 6 comment(s), 4 approved, 2 pending, 0 spam
WordPress security checklist (#18): 7 comment(s), 7 approved, 0 pending, 0 spam

Per author:
(no author): 1 comment(s), 1 approved
Bad Date: 1 comment(s), 1 approved
Bad Mail: 1 comment(s), 1 approved
Clean Reader: 1 comment(s), 1 approved
Empty Poster: 1 comment(s), 1 approved
Future Person: 1 comment(s), 1 approved
Gibberish Guy: 1 comment(s), 1 approved
Link Farmer: 1 comment(s), 1 approved
Lonely Poster: 1 comment(s), 0 approved
No Email: 1 comment(s), 1 approved
Old Post Fan: 1 comment(s), 1 approved
Pingback Bot: 1 comment(s), 1 approved
Sara Ahmed: 2 comment(s), 2 approved
Shorty: 1 comment(s), 1 approved
Spammer One: 1 comment(s), 0 approved
Stuffer: 1 comment(s), 1 approved
Tom Reed: 1 comment(s), 0 approved
Trackback Tom: 1 comment(s), 1 approved

Comments: 19, approved: 16, pending: 3, spam: 0, trash: 0, findings: 21, errors: 8, warnings: 13
```

The sample has 19 comments after the duplicate id and the
malformed row are left out. Three authors have never had a
comment approved: Tom Reed, whose only comment has sat
unapproved for 77 days, Spammer One, whose comment is the
spam-phrase hit, and Lonely Poster. The oldest comment in the
file sits on a post published 2496 days earlier, and the
pingback and trackback are mixed in with the real comments.

The reference date defaults to today. `--as-of` pins it, so the
stale day counts above are reproducible; without it the counts
move as time passes.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 wp_comment_doctor.py examples/comments.csv --as-of 2026-11-17 --check
```

On `examples/clean.csv`, three clean comments, it exits 0:

```
Per post:
How to speed up WordPress (#12): 2 comment(s), 2 approved, 0 pending, 0 spam
WordPress security checklist (#18): 1 comment(s), 1 approved, 0 pending, 0 spam

Per author:
Alice: 1 comment(s), 1 approved
Ben: 1 comment(s), 1 approved
Cara: 1 comment(s), 1 approved

Comments: 3, approved: 3, pending: 0, spam: 0, trash: 0, findings: 0, errors: 0, warnings: 0
All comments clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has three warnings, a stale
pending comment, a one-word comment, and a pingback, so it
passes `--check` (exit 0) and fails `--check --strict`
(exit 1).

`--json` emits the summary, per-post and per-author tables,
and findings as JSON:

```bash
python3 wp_comment_doctor.py examples/comments.csv --as-of 2026-11-17 --json
```

Captured output (first findings and summary):

```json
[
  {
    "comment_id": "#102",
    "rule": "stale-pending",
    "severity": "warning",
    "message": "comment has been unapproved for 77 days, above the maximum of 30",
    "action": "Approve or trash it."
  },
  {
    "comment_id": "#103",
    "rule": "spam-phrase",
    "severity": "error",
    "message": "comment contains the known spam phrase 'buy cheap'",
    "action": "Mark as spam or trash it."
  },
  {
    "comment_id": "#104",
    "rule": "too-many-links",
    "severity": "error",
    "message": "comment contains 4 links, above the maximum of 3",
    "action": "Mark as spam or trash it."
  }
]
```

```json
{
  "comments": 19,
  "approved": 16,
  "pending": 3,
  "spam": 0,
  "trash": 0,
  "findings": 21,
  "errors": 8,
  "warnings": 13,
  "post_date_column": true
}
```

`--out` writes the report to a file instead of printing it.

## Options

| Flag | Meaning |
| --- | --- |
| `--max-links` | Maximum links in a comment before it is flagged (default: 3) |
| `--max-age-days` | Days a comment may stay unapproved before it counts as stale (default: 30) |
| `--min-words` | Minimum words in a comment body (default: 3) |
| `--as-of` | Reference date as YYYY-MM-DD (default: today) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* An export with no `post_date` column still audits fully.
  Only the old-post-comment check is skipped, and a note line
  says so.
* An export with no `comment_id` column still audits, but
  duplicate ids cannot be checked. A blank id in a row that
  has the column is an error and the row is skipped.
* A duplicate comment id row is skipped from the analysis, so
  one comment cannot count twice. A duplicate comment (same
  author, same content) is kept and flagged as an error.
* A comment exactly `--max-age-days` old is not stale; only
  older than that is flagged. A comment with exactly
  `--max-links` links is not flagged; only more than that is.
* A comment with exactly `--min-words` words is not thin; only
  fewer than that is flagged.
* The `no-approved-ever` check runs on the kept comments only,
  so a duplicate id row cannot make its author look approved.
  It emits one finding per author.
* A blank line in the file is skipped silently. A row with too
  many or too few fields is a malformed-row error and is
  skipped; the rest of the file is still analyzed.
* Status matching is case-insensitive, and surrounding
  whitespace is ignored. The word `approved` and the number
  `1` both mean approved; `0`, `pending`, `hold`, and
  `unapproved` all mean pending.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

82 tests, all passing: date parsing, email validation, link
counting, spam phrase matching, keyword stuffing and gibberish
detection, status normalisation, every rule including the
stale-pending, link-count, and min-words boundaries and the
--max-links, --max-age-days, and --min-words overrides,
duplicate comments and ids, malformed rows, invalid, missing,
and future dates, BOM headers, header aliases, the
no-post-date-column note, per-post and per-author tables,
sample counts, JSON output shape, and `--check` and
`--strict` exit codes. The same 82 tests pass under pytest.

## License

MIT. See [LICENSE](LICENSE).
