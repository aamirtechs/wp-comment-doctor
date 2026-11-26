"""Tests for wp_comment_doctor."""

import csv
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import wp_comment_doctor as doctor

AS_OF = doctor.parse_as_of("2026-11-17")
HEADER = ("comment_id,post_id,post_title,author,author_email,"
          "author_url,date,status,comment_type,content,post_date")


def make_csv(rows, header=HEADER):
    """Build a CSV text from row dicts keyed by header names."""
    fields = header.split(",")
    lines = [header]
    for row in rows:
        lines.append(",".join(
            '"%s"' % str(row.get(field, "")).replace('"', '""')
            if "," in str(row.get(field, "")) or
            '"' in str(row.get(field, "")) else str(row.get(field, ""))
            for field in fields))
    return "\n".join(lines) + "\n"


def good_row(**overrides):
    """One clean approved comment, overridable per test."""
    row = {"comment_id": "1", "post_id": "12",
           "post_title": "How to speed up WordPress",
           "author": "Sara Ahmed", "author_email": "sara@example.com",
           "author_url": "", "date": "2026-11-15 09:00:00",
           "status": "1", "comment_type": "comment",
           "content": "Great guide, the caching section helped a lot.",
           "post_date": "2026-10-01"}
    row.update(overrides)
    return row


def analyze(rows, header=HEADER, **kwargs):
    """Write rows to a temp CSV and run analyze_file on it."""
    text = make_csv(rows, header)
    with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                     delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        return doctor.analyze_file(path, as_of=AS_OF, **kwargs)
    finally:
        os.unlink(path)


def rules(report):
    """Return the set of rule names in a report."""
    return {finding["rule"] for finding in report["findings"]}


def findings_for(report, rule):
    """Return the findings in a report with the given rule."""
    return [finding for finding in report["findings"]
            if finding["rule"] == rule]


class TestParseDate(unittest.TestCase):
    def test_datetime(self):
        self.assertEqual(doctor.parse_date("2026-11-15 09:00:00")
                         .isoformat(), "2026-11-15")

    def test_iso_datetime(self):
        self.assertEqual(doctor.parse_date("2026-11-15T09:00:00")
                         .isoformat(), "2026-11-15")

    def test_plain_date(self):
        self.assertEqual(doctor.parse_date("2026-11-15").isoformat(),
                         "2026-11-15")

    def test_slash_date(self):
        self.assertEqual(doctor.parse_date("2026/11/15").isoformat(),
                         "2026-11-15")

    def test_day_first_date(self):
        self.assertEqual(doctor.parse_date("15/11/2026").isoformat(),
                         "2026-11-15")

    def test_blank_is_none(self):
        self.assertIsNone(doctor.parse_date(""))

    def test_garbage_is_none(self):
        self.assertIsNone(doctor.parse_date("not-a-date"))

    def test_whitespace_is_stripped(self):
        self.assertEqual(doctor.parse_date(" 2026-11-15 ")
                         .isoformat(), "2026-11-15")


class TestEmail(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(doctor.is_valid_email("sara@example.com"))

    def test_missing_at(self):
        self.assertFalse(doctor.is_valid_email("not-an-email"))

    def test_missing_domain(self):
        self.assertFalse(doctor.is_valid_email("sara@"))

    def test_spaces_rejected(self):
        self.assertFalse(doctor.is_valid_email("sara @example.com"))


class TestSpamHelpers(unittest.TestCase):
    def test_link_count_http(self):
        self.assertEqual(doctor.count_links(
            "see https://a.example.com and http://b.example.com"), 2)

    def test_link_count_www(self):
        self.assertEqual(doctor.count_links("visit www.example.com"), 1)

    def test_link_count_none(self):
        self.assertEqual(doctor.count_links("no links here"), 0)

    def test_spam_phrase_found(self):
        self.assertEqual(doctor.find_spam_phrase(
            "Buy cheap stuff today"), "buy cheap")

    def test_spam_phrase_case_insensitive(self):
        self.assertEqual(doctor.find_spam_phrase(
            "VIAGRA for sale"), "viagra")

    def test_spam_phrase_none(self):
        self.assertIsNone(doctor.find_spam_phrase(
            "Great guide, thank you."))

    def test_keyword_stuffing(self):
        self.assertEqual(doctor.is_keyword_stuffed(
            "great great great great great great great great"),
            "great")

    def test_keyword_stuffing_short_words_ignored(self):
        self.assertIsNone(doctor.is_keyword_stuffed(
            "the the the the the the the the"))

    def test_keyword_stuffing_below_threshold(self):
        self.assertIsNone(doctor.is_keyword_stuffed(
            "great guide, great tips, great photos, great stuff"))

    def test_gibberish_repeated_chars(self):
        self.assertIsNotNone(doctor.is_gibberish("aaaaaa bbbb"))

    def test_gibberish_consonant_run(self):
        self.assertIsNotNone(doctor.is_gibberish(
            "bcdfghjklmnpqrstvwxyz word"))

    def test_gibberish_non_ascii(self):
        self.assertIsNotNone(doctor.is_gibberish(
            "привет привет привет привет привет hello"))

    def test_gibberish_normal_text(self):
        self.assertIsNone(doctor.is_gibberish(
            "Great guide, the caching section helped a lot."))

    def test_status_values(self):
        self.assertEqual(doctor.normalise_status("1"), "approved")
        self.assertEqual(doctor.normalise_status("approved"),
                         "approved")
        self.assertEqual(doctor.normalise_status("0"), "pending")
        self.assertEqual(doctor.normalise_status("hold"), "pending")
        self.assertEqual(doctor.normalise_status("spam"), "spam")
        self.assertEqual(doctor.normalise_status("trash"), "trash")
        self.assertIsNone(doctor.normalise_status("weird"))
        self.assertEqual(doctor.normalise_status(" APPROVED "),
                         "approved")


class TestRules(unittest.TestCase):
    def test_clean_row_has_no_findings(self):
        report = analyze([good_row()])
        self.assertEqual(report["summary"]["findings"], 0)
        self.assertEqual(report["summary"]["comments"], 1)

    def test_stale_pending(self):
        report = analyze([good_row(comment_id="1", status="0",
                                   date="2026-09-01 10:00:00")])
        self.assertIn("stale-pending", rules(report))

    def test_stale_pending_boundary_not_flagged(self):
        report = analyze([good_row(comment_id="1", status="0",
                                   date="2026-10-18 09:00:00")])
        self.assertNotIn("stale-pending", rules(report))

    def test_stale_pending_approved_not_flagged(self):
        report = analyze([good_row(date="2026-09-01 10:00:00")])
        self.assertNotIn("stale-pending", rules(report))

    def test_max_age_days_override(self):
        report = analyze([good_row(comment_id="1", status="0",
                                   date="2026-09-01 10:00:00")],
                         max_age_days=90)
        self.assertNotIn("stale-pending", rules(report))

    def test_spam_phrase(self):
        report = analyze([good_row(
            content="Buy cheap viagra now, act fast!")])
        found = findings_for(report, "spam-phrase")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "error")

    def test_too_many_links(self):
        report = analyze([good_row(content=(
            "See https://a.example.com https://b.example.com "
            "https://c.example.com https://d.example.com now"))])
        self.assertIn("too-many-links", rules(report))

    def test_link_limit_boundary(self):
        report = analyze([good_row(content=(
            "See https://a.example.com https://b.example.com "
            "https://c.example.com now"))])
        self.assertNotIn("too-many-links", rules(report))

    def test_max_links_override(self):
        report = analyze([good_row(content=(
            "See https://a.example.com https://b.example.com "
            "https://c.example.com https://d.example.com now"))],
                         max_links=5)
        self.assertNotIn("too-many-links", rules(report))

    def test_duplicate_comment(self):
        report = analyze([good_row(comment_id="1"),
                          good_row(comment_id="2")])
        found = findings_for(report, "duplicate-comment")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["comment_id"], "#2")

    def test_duplicate_comment_case_insensitive(self):
        report = analyze([good_row(comment_id="1"),
                          good_row(comment_id="2",
                                   author="sara ahmed",
                                   content="great guide, the caching "
                                           "section helped a lot.")])
        self.assertIn("duplicate-comment", rules(report))

    def test_same_content_different_author_not_duplicate(self):
        report = analyze([good_row(comment_id="1"),
                          good_row(comment_id="2", author="Ben")])
        self.assertNotIn("duplicate-comment", rules(report))

    def test_duplicate_comment_id_skips_row(self):
        report = analyze([good_row(comment_id="1"),
                          good_row(comment_id="1", author="Ben")])
        self.assertIn("duplicate-comment-id", rules(report))
        self.assertEqual(report["summary"]["comments"], 1)

    def test_missing_comment_id(self):
        report = analyze([good_row(comment_id="")])
        self.assertIn("missing-comment-id", rules(report))
        self.assertEqual(report["summary"]["comments"], 0)

    def test_missing_author(self):
        report = analyze([good_row(author="")])
        found = findings_for(report, "missing-author")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "error")

    def test_missing_email(self):
        report = analyze([good_row(author_email="")])
        self.assertIn("missing-email", rules(report))

    def test_invalid_email(self):
        report = analyze([good_row(author_email="not-an-email")])
        found = findings_for(report, "invalid-email")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "error")

    def test_invalid_date(self):
        report = analyze([good_row(date="not-a-date")])
        found = findings_for(report, "invalid-date")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")

    def test_future_date(self):
        report = analyze([good_row(date="2027-01-01 09:00:00")])
        self.assertIn("future-date", rules(report))

    def test_old_post_comment(self):
        report = analyze([good_row(date="2026-11-01 09:00:00",
                                   post_date="2020-01-01")])
        self.assertIn("old-post-comment", rules(report))

    def test_recent_post_not_flagged(self):
        report = analyze([good_row()])
        self.assertNotIn("old-post-comment", rules(report))

    def test_no_approved_ever(self):
        report = analyze([good_row(comment_id="1", status="0",
                                   date="2026-11-10 09:00:00")])
        found = findings_for(report, "no-approved-ever")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["comment_id"], "Sara Ahmed")

    def test_no_approved_ever_one_per_author(self):
        report = analyze([
            good_row(comment_id="1", status="0",
                     date="2026-11-10 09:00:00"),
            good_row(comment_id="2", status="0",
                     date="2026-11-11 09:00:00",
                     content="Another pending comment here.")])
        self.assertEqual(len(findings_for(report, "no-approved-ever")),
                         1)

    def test_approved_author_not_flagged(self):
        report = analyze([good_row()])
        self.assertNotIn("no-approved-ever", rules(report))

    def test_pingback_mixed(self):
        report = analyze([good_row(comment_type="pingback")])
        self.assertIn("pingback-mixed", rules(report))

    def test_trackback_mixed(self):
        report = analyze([good_row(comment_type="trackback")])
        self.assertIn("pingback-mixed", rules(report))

    def test_empty_content(self):
        report = analyze([good_row(content="")])
        self.assertIn("empty-content", rules(report))
        self.assertNotIn("thin-comment", rules(report))

    def test_thin_comment(self):
        report = analyze([good_row(content="Nice!")])
        self.assertIn("thin-comment", rules(report))

    def test_min_words_override(self):
        report = analyze([good_row(content="Nice!")], min_words=1)
        self.assertNotIn("thin-comment", rules(report))

    def test_keyword_stuffing_rule(self):
        report = analyze([good_row(
            content="great great great great great great great "
                    "great")])
        self.assertIn("keyword-stuffing", rules(report))

    def test_gibberish_rule(self):
        report = analyze([good_row(
            content="asdfghjkl qwertyuiop zzzzzzzzzzz")])
        self.assertIn("gibberish-content", rules(report))

    def test_unknown_status(self):
        report = analyze([good_row(status="weird")])
        self.assertIn("unknown-status", rules(report))

    def test_malformed_row(self):
        text = HEADER + "\n1,12,Title\n"
        with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                        delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            report = doctor.analyze_file(path, as_of=AS_OF)
        finally:
            os.unlink(path)
        self.assertIn("malformed-row", rules(report))
        self.assertEqual(report["summary"]["comments"], 0)

    def test_blank_lines_skipped(self):
        text = make_csv([good_row()]) + "\n\n"
        with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                        delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            report = doctor.analyze_file(path, as_of=AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(report["summary"]["comments"], 1)
        self.assertEqual(report["summary"]["findings"], 0)

    def test_bom_header(self):
        text = "\ufeff" + make_csv([good_row()])
        with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                        delete=False,
                                        encoding="utf-8") as handle:
            handle.write(text)
            path = handle.name
        try:
            report = doctor.analyze_file(path, as_of=AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(report["summary"]["comments"], 1)
        self.assertEqual(report["summary"]["findings"], 0)

    def test_header_aliases(self):
        header = ("id,post,post,comment_author,comment_author_email,"
                  "comment_date_gmt,comment_approved,type,comment")
        row = {"id": "1", "post": "12",
               "comment_author": "Sara Ahmed",
               "comment_author_email": "sara@example.com",
               "comment_date_gmt": "2026-11-15 09:00:00",
               "comment_approved": "1", "type": "comment",
               "comment": "Great guide, the caching section helped."}
        report = analyze([row], header=header)
        self.assertEqual(report["summary"]["comments"], 1)
        self.assertEqual(report["summary"]["findings"], 0)

    def test_missing_required_column_raises(self):
        header = "comment_id,author,date,status"
        with self.assertRaises(ValueError):
            analyze([good_row()], header=header)

    def test_empty_file_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                        delete=False) as handle:
            path = handle.name
        try:
            with self.assertRaises(ValueError):
                doctor.analyze_file(path, as_of=AS_OF)
        finally:
            os.unlink(path)

    def test_no_post_date_column_note(self):
        header = ("comment_id,post_id,post_title,author,author_email,"
                  "author_url,date,status,comment_type,content")
        report = analyze([good_row()], header=header)
        self.assertFalse(report["summary"]["post_date_column"])
        text = doctor.format_text(report)
        self.assertIn("no post_date column found", text)


class TestSummaries(unittest.TestCase):
    def test_per_post_table(self):
        report = analyze([
            good_row(comment_id="1"),
            good_row(comment_id="2", author="Ben",
                     status="0", date="2026-11-10 09:00:00",
                     content="Another comment on this post."),
            good_row(comment_id="3", author="Cara", post_id="18",
                     post_title="Security checklist",
                     content="Useful checklist, thank you.")])
        self.assertEqual(len(report["posts"]), 2)
        first = report["posts"][0]
        self.assertEqual(first["post"],
                         "How to speed up WordPress (#12)")
        self.assertEqual(first["comments"], 2)
        self.assertEqual(first["approved"], 1)
        self.assertEqual(first["pending"], 1)

    def test_per_author_table(self):
        report = analyze([
            good_row(comment_id="1"),
            good_row(comment_id="2",
                     content="A second comment from Sara here.")])
        self.assertEqual(len(report["authors"]), 1)
        self.assertEqual(report["authors"][0]["author"], "Sara Ahmed")
        self.assertEqual(report["authors"][0]["comments"], 2)
        self.assertEqual(report["authors"][0]["approved"], 2)

    def test_status_counts(self):
        report = analyze([
            good_row(comment_id="1"),
            good_row(comment_id="2", author="Ben", status="spam",
                     content="Buy cheap stuff now, act fast."),
            good_row(comment_id="3", author="Cara", status="trash",
                     content="Old comment to delete.")])
        summary = report["summary"]
        self.assertEqual(summary["approved"], 1)
        self.assertEqual(summary["spam"], 1)
        self.assertEqual(summary["trash"], 1)

    def test_sample_counts(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "comments.csv")
        report = doctor.analyze_file(path, as_of=AS_OF)
        summary = report["summary"]
        self.assertEqual(summary["comments"], 19)
        self.assertEqual(summary["approved"], 16)
        self.assertEqual(summary["pending"], 3)
        self.assertEqual(summary["findings"], 21)
        self.assertEqual(summary["errors"], 8)
        self.assertEqual(summary["warnings"], 13)

    def test_clean_sample(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        report = doctor.analyze_file(path, as_of=AS_OF)
        self.assertEqual(report["summary"]["findings"], 0)
        self.assertEqual(report["summary"]["comments"], 3)

    def test_warnings_only_sample(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        report = doctor.analyze_file(path, as_of=AS_OF)
        self.assertEqual(report["summary"]["findings"], 3)
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["warnings"], 3)


class TestOutput(unittest.TestCase):
    def test_text_output_has_tables(self):
        report = analyze([good_row()])
        text = doctor.format_text(report)
        self.assertIn("Per post:", text)
        self.assertIn("Per author:", text)
        self.assertIn("All comments clean.", text)

    def test_json_output_shape(self):
        report = analyze([good_row()])
        data = json.loads(doctor.format_json(report))
        self.assertIn("summary", data)
        self.assertIn("posts", data)
        self.assertIn("authors", data)
        self.assertIn("findings", data)
        self.assertEqual(data["summary"]["comments"], 1)

    def test_finding_dict_shape(self):
        report = analyze([good_row(author="")])
        finding = report["findings"][0]
        self.assertEqual(set(finding),
                         {"comment_id", "rule", "severity", "message"})


class TestCli(unittest.TestCase):
    def run_main(self, argv):
        """Run main() capturing stdout and stderr."""
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            code = doctor.main(argv)
            return code, sys.stdout.getvalue(), sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def test_check_fails_on_errors(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "comments.csv")
        code, _, _ = self.run_main(
            [path, "--as-of", "2026-11-17", "--check"])
        self.assertEqual(code, 1)

    def test_check_passes_on_clean(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        code, _, _ = self.run_main(
            [path, "--as-of", "2026-11-17", "--check"])
        self.assertEqual(code, 0)

    def test_strict_fails_on_warnings(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        code, _, _ = self.run_main(
            [path, "--as-of", "2026-11-17", "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_check_passes_on_warnings_only(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        code, _, _ = self.run_main(
            [path, "--as-of", "2026-11-17", "--check"])
        self.assertEqual(code, 0)

    def test_missing_file_exits_2(self):
        code, _, err = self.run_main(["/tmp/no-such-file.csv"])
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)

    def test_bad_as_of_exits_2(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        code, _, err = self.run_main([path, "--as-of", "nope"])
        self.assertEqual(code, 2)
        self.assertIn("--as-of", err)

    def test_out_writes_file(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                        delete=False) as handle:
            out_path = handle.name
        try:
            code, stdout, _ = self.run_main(
                [path, "--as-of", "2026-11-17", "--out", out_path])
            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            with open(out_path) as handle:
                self.assertIn("All comments clean.", handle.read())
        finally:
            os.unlink(out_path)

    def test_json_flag(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        code, stdout, _ = self.run_main(
            [path, "--as-of", "2026-11-17", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(data["summary"]["comments"], 3)


if __name__ == "__main__":
    unittest.main()
