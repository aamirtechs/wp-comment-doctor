# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a custom spam phrases file

Title: Let teams supply their own spam phrases

Description: Add a --spam-phrases flag that reads a file of spam
phrases (one per line) and uses it instead of the built-in list,
so a team can flag the phrases its own site attracts without
changing the code. Lines starting with # are comments and are
ignored, and matching stays case-insensitive.

Difficulty: Easy

Acceptance criteria: a file containing "free cruise" flags a
comment with that phrase and does not flag the built-in phrase
"buy cheap"; without the flag the built-in list still applies;
a test covers both cases; README documents the flag.

## 2. Add a per-author spam score column

Title: Show a spam score per author in the report

Description: Add a --scores flag that prints, after the
per-author table, one line per author with a simple spam score:
one point per error finding on their comments plus one point
per two warnings, sorted with the highest score first, so a
moderator can see at a glance which authors to block first.
Authors with no findings score 0 and are left out.

Difficulty: Easy

Acceptance criteria: the scores for the sample file show
Spammer One at 1 and Link Farmer at 1 with Tom Reed at 0 left
out; a test checks the ordering; README documents the flag.

## 3. Support the wp comment list JSON export

Title: Accept wp comment list --format=json input

Description: Add a --format json option so the tool can read
the JSON output of `wp comment list --format=json` directly,
with the same checks and the same output. The JSON objects
carry the same field names as the CSV columns.

Difficulty: Medium

Acceptance criteria: the sample comments as JSON produce the
same 21 findings as the CSV; a test round-trips both formats;
README documents the option.

## 4. Add a suggested-action line per finding

Title: Print what to do about each flagged comment

Description: Each finding already says what is wrong. Add a
short suggested action to the text output, for example
"Approve or trash it" for a stale-pending comment and "Block
the author" for a spam-phrase comment, so a moderator can work
through the queue without guessing the next step.

Difficulty: Easy

Acceptance criteria: every rule has a suggested action; the
sample output shows the action on the stale-pending and
spam-phrase lines; a test checks that each rule maps to an
action; README documents the lines.
