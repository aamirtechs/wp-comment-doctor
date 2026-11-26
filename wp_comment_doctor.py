"""WordPress comments CSV audit CLI.

Reads a WordPress comments CSV export (from `wp comment list
--format=csv`, or from the comment moderation screen) and audits
it for the comments that most often signal spam, neglect, or a
broken moderation queue: comments stuck unapproved for weeks,
spam-pattern comments (excessive links, known spam phrases,
keyword stuffing, gibberish bursts), duplicate comments from
the same author, comments on very old posts, comments from
authors who have never had one approved, pingbacks and
trackbacks mixed in with real comments, and bad data such as
missing authors or emails, invalid or future dates, duplicate
comment ids, and malformed rows.

A WordPress site with comments left unmoderated for months is
a spam magnet: search engines index the junk, real readers stop
commenting, and a single unapproved thread can hide a genuine
question from a paying customer. WP-CLI lists comments but
does not score them, and the moderation screen shows one page
at a time. This tool is the offline audit of the exported
list: it reads the file, flags every problem with a rule name
and a severity, and never touches the site.

Each problem is a finding with a comment id, a rule name, a
severity (error or warning), and a message. Errors are the
ones that are live spam or break the audit; warnings are
comments worth following up. --check exits 1 when any error
is found, and --strict also fails on warnings.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 wp_comment_doctor.py examples/comments.csv --as-of 2026-11-17
    python3 wp_comment_doctor.py comments.csv --json --check
    python3 wp_comment_doctor.py comments.csv --max-links 2 --max-age-days 14
"""

import argparse
import csv
import datetime
import json
import re
import sys
from collections import Counter

__version__ = "1.0.0"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    "%Y/%m/%d", "%d/%m/%Y",
)

LINK_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z]+")
REPEATED_CHAR_RE = re.compile(r"(.)\1{5,}")
CONSONANT_RUN_RE = re.compile(r"[bcdfghjklmnpqrstvwxz]{10,}",
                               re.IGNORECASE)

# Phrases that appear in comment spam far more often than in
# genuine comments. Matched case-insensitively as substrings.
SPAM_PHRASES = (
    "buy cheap", "viagra", "cialis", "casino", "make money fast",
    "get rich quick", "free followers", "crypto", "bitcoin",
    "payday loan", "weight loss", "essay writing service",
    "click here to win", "limited time offer", "guaranteed income",
    "act now", "double your money", "work from home",
)

# WordPress comment statuses, after normalising case and
# whitespace. "1" and "0" are what wp comment list exports.
APPROVED_VALUES = ("1", "approved", "approve", "yes")
PENDING_VALUES = ("0", "pending", "hold", "unapproved", "moderated")
SPAM_VALUES = ("spam",)
TRASH_VALUES = ("trash", "deleted")

# Header aliases: the export column names this tool accepts.
COLUMN_ALIASES = {
    "comment_id": ("comment_id", "comment_ID", "id", "ID"),
    "post_id": ("post_id", "comment_post_ID", "post"),
    "post_title": ("post_title", "post", "title"),
    "author": ("author", "comment_author", "comment_author_name",
               "author_name"),
    "author_email": ("author_email", "comment_author_email",
                     "email"),
    "author_url": ("author_url", "comment_author_url", "url",
                   "website"),
    "date": ("date", "comment_date", "comment_date_gmt",
             "created", "comment_created"),
    "status": ("status", "comment_approved", "approved",
               "comment_status"),
    "content": ("content", "comment_content", "comment"),
    "comment_type": ("comment_type", "type", "comment_type_name"),
    "post_date": ("post_date", "post_published", "published",
                  "post_published_date"),
}

REQUIRED_COLUMNS = ("author", "date", "status", "content")

DEFAULT_MAX_LINKS = 3
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MIN_WORDS = 3
OLD_POST_DAYS = 365


RULE_ACTIONS = {
    "spam-phrase": "Mark as spam or trash it.",
    "too-many-links": "Mark as spam or trash it.",
    "duplicate-comment": "Trash the duplicate comment.",
    "duplicate-comment-id": "Remove the duplicate row from the export.",
    "missing-comment-id": "Fix or remove the row so the comment can be tracked.",
    "missing-author": "Add the author or remove the comment.",
    "missing-email": "Add the author email or remove the comment.",
    "invalid-email": "Fix the author email or remove the comment.",
    "invalid-date": "Fix the comment date.",
    "future-date": "Fix the comment date.",
    "unknown-status": "Fix the comment status.",
    "pingback-mixed": "Separate or remove the pingback/trackback.",
    "empty-content": "Remove the empty comment.",
    "keyword-stuffing": "Review and mark as spam or trash it.",
    "gibberish-content": "Review and mark as spam or trash it.",
    "thin-comment": "Review and approve or trash it.",
    "stale-pending": "Approve or trash it.",
    "old-post-comment": "Review and approve, close, or trash it.",
    "no-approved-ever": "Review the author's comments before approving.",
    "malformed-row": "Fix the row in the CSV export.",
}


class Finding:
    """One audit finding for one comment or for the site."""

    def __init__(self, comment_id, rule, severity, message):
        self.comment_id = comment_id
        self.rule = rule
        self.severity = severity
        self.message = message
        self.action = RULE_ACTIONS.get(rule, "Review the comment.")

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"comment_id": self.comment_id, "rule": self.rule,
                "severity": self.severity, "message": self.message,
                "action": self.action}

    def __str__(self):
        return "%s [%s] %s: %s Action: %s" % (
            self.severity.upper(), self.rule, self.comment_id,
            self.message, self.action)


def parse_date(value):
    """Parse a date string, or return None when unrecognised."""
    value = value.strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def is_valid_email(email):
    """Return True when the email looks like a real address."""
    return bool(EMAIL_RE.match(email.strip()))


def count_links(content):
    """Count URLs in a comment body."""
    return len(LINK_RE.findall(content))


def find_spam_phrase(content):
    """Return the first known spam phrase found, or None."""
    lowered = content.lower()
    for phrase in SPAM_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def most_common_word(content):
    """Return (word, count) for the most repeated word, or None."""
    words = [word.lower() for word in WORD_RE.findall(content)
             if len(word) >= 4]
    if not words:
        return None
    word, count = Counter(words).most_common(1)[0]
    return word, count


def is_keyword_stuffed(content):
    """Return the stuffed word, or None.

    A comment is stuffed when one word of four or more letters
    appears at least five times and makes up at least a quarter
    of the long words in the comment.
    """
    result = most_common_word(content)
    if result is None:
        return None
    word, count = result
    long_words = [w for w in WORD_RE.findall(content) if len(w) >= 4]
    if count >= 5 and count * 4 >= len(long_words):
        return word
    return None


def is_gibberish(content):
    """Return a reason the content looks like gibberish, or None."""
    letters = [char for char in content if char.isalpha()]
    if not letters:
        return None
    non_ascii = sum(1 for char in letters if ord(char) > 127)
    if non_ascii * 5 > len(letters) * 2:
        return "more than 40% of the letters are non-ASCII"
    if REPEATED_CHAR_RE.search(content):
        return "contains a run of the same character repeated 6 or more times"
    if CONSONANT_RUN_RE.search(content):
        return "contains a run of 10 or more consonants"
    return None


def normalise_status(value):
    """Map a raw status value to approved, pending, spam, trash."""
    value = value.strip().lower()
    if value in APPROVED_VALUES:
        return "approved"
    if value in PENDING_VALUES:
        return "pending"
    if value in SPAM_VALUES:
        return "spam"
    if value in TRASH_VALUES:
        return "trash"
    return None


def resolve_columns(header):
    """Map canonical column names to header positions."""
    lowered = [name.strip().lower() for name in header]
    columns = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lowered:
                columns[canonical] = lowered.index(alias.lower())
                break
    return columns


class Comment:
    """One comment row from the export."""

    def __init__(self, row, columns):
        def get(name):
            if name not in columns:
                return ""
            return row[columns[name]].strip()

        self.comment_id = get("comment_id")
        self.post_id = get("post_id")
        self.post_title = get("post_title")
        self.author = get("author")
        self.author_email = get("author_email")
        self.author_url = get("author_url")
        self.date_raw = get("date")
        self.status_raw = get("status")
        self.content = get("content")
        self.comment_type = get("comment_type").lower()
        self.post_date_raw = get("post_date")
        self.date = parse_date(self.date_raw)
        self.post_date = parse_date(self.post_date_raw)
        self.status = normalise_status(self.status_raw)

    @property
    def label(self):
        """Short label used in findings: the comment id or author."""
        if self.comment_id:
            return "#%s" % self.comment_id
        if self.author:
            return self.author
        return "(no id)"

    @property
    def post_label(self):
        """Label for the per-post table."""
        if self.post_title and self.post_id:
            return "%s (#%s)" % (self.post_title, self.post_id)
        if self.post_title:
            return self.post_title
        if self.post_id:
            return "#%s" % self.post_id
        return "(no post)"

    @property
    def word_count(self):
        """Number of words in the comment body."""
        return len(WORD_RE.findall(self.content))


def load_comments(path, as_of, max_links, max_age_days, min_words):
    """Read the CSV and audit every row. Returns report pieces."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("file is empty, no header row found")
        columns = resolve_columns(header)
        missing = [name for name in REQUIRED_COLUMNS
                   if name not in columns]
        if missing:
            raise ValueError(
                "missing required column(s): %s" % ", ".join(missing))
        has_post_date = "post_date" in columns
        has_comment_id = "comment_id" in columns
        comments = []
        findings = []
        seen_ids = set()
        seen_comments = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, so the "
                    "row was skipped" % (len(row), len(header))))
                continue
            comment = Comment(row, columns)
            if has_comment_id:
                if not comment.comment_id:
                    findings.append(Finding(
                        "row %d" % line_number, "missing-comment-id",
                        "error", "row has no comment id, so the row "
                        "was skipped"))
                    continue
                if comment.comment_id in seen_ids:
                    findings.append(Finding(
                        comment.label, "duplicate-comment-id",
                        "error", "comment id already appears in this "
                        "export, so this duplicate row was skipped"))
                    continue
                seen_ids.add(comment.comment_id)
            if not comment.author:
                findings.append(Finding(
                    comment.label, "missing-author", "error",
                    "comment has no author, so it cannot be "
                    "attributed or replied to"))
            if not comment.author_email:
                findings.append(Finding(
                    comment.label, "missing-email", "error",
                    "comment has no author email, so the author "
                    "cannot be contacted"))
            elif not is_valid_email(comment.author_email):
                findings.append(Finding(
                    comment.label, "invalid-email", "error",
                    "email %r is missing or not a valid email "
                    "address" % comment.author_email))
            if comment.date is None:
                findings.append(Finding(
                    comment.label, "invalid-date", "warning",
                    "date %r is not a recognised date"
                    % comment.date_raw))
            elif comment.date > as_of:
                findings.append(Finding(
                    comment.label, "future-date", "warning",
                    "date %s is in the future" % comment.date))
            if comment.status is None:
                findings.append(Finding(
                    comment.label, "unknown-status", "warning",
                    "status %r is not a recognised WordPress "
                    "comment status" % comment.status_raw))
            if comment.comment_type in ("pingback", "trackback"):
                findings.append(Finding(
                    comment.label, "pingback-mixed", "warning",
                    "this is a %s, not a real comment, and it is "
                    "mixed in with the comments"
                    % comment.comment_type))
            if not comment.content:
                findings.append(Finding(
                    comment.label, "empty-content", "warning",
                    "comment has no content"))
            else:
                links = count_links(comment.content)
                if links > max_links:
                    findings.append(Finding(
                        comment.label, "too-many-links", "error",
                        "comment contains %d links, above the "
                        "maximum of %d" % (links, max_links)))
                phrase = find_spam_phrase(comment.content)
                if phrase:
                    findings.append(Finding(
                        comment.label, "spam-phrase", "error",
                        "comment contains the known spam phrase "
                        "%r" % phrase))
                stuffed = is_keyword_stuffed(comment.content)
                if stuffed:
                    findings.append(Finding(
                        comment.label, "keyword-stuffing", "warning",
                        "the word %r is repeated so often the "
                        "comment reads as keyword stuffing"
                        % stuffed))
                gibberish = is_gibberish(comment.content)
                if gibberish:
                    findings.append(Finding(
                        comment.label, "gibberish-content", "warning",
                        "comment looks like gibberish: %s"
                        % gibberish))
                if comment.word_count < min_words:
                    findings.append(Finding(
                        comment.label, "thin-comment", "warning",
                        "comment has only %d word(s), below the "
                        "minimum of %d" % (comment.word_count,
                                           min_words)))
            if (comment.status == "pending" and comment.date
                    and (as_of - comment.date).days > max_age_days):
                findings.append(Finding(
                    comment.label, "stale-pending", "warning",
                    "comment has been unapproved for %d days, "
                    "above the maximum of %d"
                    % ((as_of - comment.date).days, max_age_days)))
            if (has_post_date and comment.post_date and comment.date
                    and (comment.date - comment.post_date).days
                    > OLD_POST_DAYS):
                findings.append(Finding(
                    comment.label, "old-post-comment", "warning",
                    "comment is on a post published %d days "
                    "before the comment"
                    % (comment.date - comment.post_date).days))
            if comment.author and comment.content:
                key = (comment.author.lower(),
                       " ".join(comment.content.lower().split()))
                if key in seen_comments:
                    findings.append(Finding(
                        comment.label, "duplicate-comment", "error",
                        "same author and same content as an earlier "
                        "comment, so this looks like a duplicate "
                        "submission"))
                else:
                    seen_comments.add(key)
            comments.append(comment)
    return comments, findings, has_post_date


def analyze_file(path, as_of=None, max_links=DEFAULT_MAX_LINKS,
                 max_age_days=DEFAULT_MAX_AGE_DAYS,
                 min_words=DEFAULT_MIN_WORDS):
    """Audit one comments file and return the report dict."""
    if as_of is None:
        as_of = datetime.date.today()
    comments, findings, has_post_date = load_comments(
        path, as_of, max_links, max_age_days, min_words)
    approved_authors = {comment.author.lower()
                        for comment in comments
                        if comment.status == "approved"
                        and comment.author}
    for author in sorted({comment.author for comment in comments
                          if comment.author}):
        if author.lower() not in approved_authors:
            count = sum(1 for comment in comments
                        if comment.author == author)
            findings.append(Finding(
                author, "no-approved-ever", "warning",
                "author has no approved comment in this export "
                "(%d comment(s), all unapproved, spam, or trash)"
                % count))
    post_counts = {}
    for comment in comments:
        entry = post_counts.setdefault(
            comment.post_label,
            {"comments": 0, "approved": 0, "pending": 0, "spam": 0})
        entry["comments"] += 1
        if comment.status in entry:
            entry[comment.status] += 1
    post_rows = [{"post": label, "comments": entry["comments"],
                  "approved": entry["approved"],
                  "pending": entry["pending"],
                  "spam": entry["spam"]}
                 for label, entry in sorted(post_counts.items())]
    author_counts = {}
    for comment in comments:
        entry = author_counts.setdefault(
            comment.author or "(no author)",
            {"comments": 0, "approved": 0})
        entry["comments"] += 1
        if comment.status == "approved":
            entry["approved"] += 1
    author_rows = [{"author": author,
                    "comments": entry["comments"],
                    "approved": entry["approved"]}
                   for author, entry in sorted(author_counts.items())]
    status_counts = Counter(comment.status for comment in comments
                            if comment.status)
    summary = {
        "comments": len(comments),
        "approved": status_counts.get("approved", 0),
        "pending": status_counts.get("pending", 0),
        "spam": status_counts.get("spam", 0),
        "trash": status_counts.get("trash", 0),
        "findings": len(findings),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings
                        if f.severity == "warning"),
        "post_date_column": has_post_date,
    }
    return {"summary": summary, "posts": post_rows,
            "authors": author_rows,
            "findings": [f.as_dict() for f in findings]}


def format_text(report):
    """Render the audit as plain text."""
    summary = report["summary"]
    lines = []
    for finding in report["findings"]:
        lines.append("%s [%s] %s: %s Action: %s"
                     % (finding["severity"].upper(),
                        finding["rule"], finding["comment_id"],
                        finding["message"], finding["action"]))
    if report["posts"]:
        lines.append("")
        lines.append("Per post:")
        for row in report["posts"]:
            lines.append("%s: %d comment(s), %d approved, %d "
                         "pending, %d spam"
                         % (row["post"], row["comments"],
                            row["approved"], row["pending"],
                            row["spam"]))
    if report["authors"]:
        lines.append("")
        lines.append("Per author:")
        for row in report["authors"]:
            lines.append("%s: %d comment(s), %d approved"
                         % (row["author"], row["comments"],
                            row["approved"]))
    lines.append("")
    lines.append("Comments: %d, approved: %d, pending: %d, spam: %d, "
                 "trash: %d, findings: %d, errors: %d, warnings: %d"
                 % (summary["comments"], summary["approved"],
                    summary["pending"], summary["spam"],
                    summary["trash"], summary["findings"],
                    summary["errors"], summary["warnings"]))
    if not summary["post_date_column"]:
        lines.append("Note: no post_date column found, so "
                     "old-post-comment checks were skipped.")
    if not report["findings"]:
        lines.append("All comments clean.")
    return "\n".join(lines) + "\n"


def format_json(report):
    """Render the audit as JSON."""
    return json.dumps(report, indent=2) + "\n"


def parse_as_of(value):
    """Parse a YYYY-MM-DD reference date, or raise ValueError."""
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            "--as-of must be a YYYY-MM-DD date, got %r" % value)


def main(argv=None):
    """Entry point for the wp-comment-doctor CLI."""
    parser = argparse.ArgumentParser(
        description="Audit a WordPress comments CSV export for "
                    "stale unapproved comments, spam patterns, "
                    "duplicate comments, comments on old posts, "
                    "authors with no approved comment, and bad data.")
    parser.add_argument("path", help="CSV file of WordPress comments")
    parser.add_argument("--max-links", type=int,
                        default=DEFAULT_MAX_LINKS,
                        help="maximum links in a comment before it "
                             "is flagged (default: 3)")
    parser.add_argument("--max-age-days", type=int,
                        default=DEFAULT_MAX_AGE_DAYS,
                        help="days a comment may stay unapproved "
                             "before it counts as stale "
                             "(default: 30)")
    parser.add_argument("--min-words", type=int,
                        default=DEFAULT_MIN_WORDS,
                        help="minimum words in a comment body "
                             "(default: 3)")
    parser.add_argument("--as-of", default=None,
                        help="reference date as YYYY-MM-DD "
                             "(default: today)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", help="write the report to a file")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    try:
        as_of = parse_as_of(args.as_of) if args.as_of else None
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    try:
        report = analyze_file(args.path, as_of=as_of,
                              max_links=args.max_links,
                              max_age_days=args.max_age_days,
                              min_words=args.min_words)
    except FileNotFoundError:
        print("error: file not found: %s" % args.path, file=sys.stderr)
        return 2
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: cannot read %s: %s" % (args.path, exc),
              file=sys.stderr)
        return 2
    if args.json:
        output = format_json(report)
    else:
        output = format_text(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output, end="")
    summary = report["summary"]
    if args.check:
        if summary["errors"]:
            return 1
        if args.strict and summary["warnings"]:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
