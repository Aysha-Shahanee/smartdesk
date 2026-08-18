"""Redaction for window and calendar titles.

Window titles are the most sensitive thing this application records, and the
only recorded field that is free text written by software the user does not
control. A browser puts the whole URL in there, query string included; an editor
puts the absolute path of the file; a mail client puts the subject line and the
correspondent. Any of those can carry a client name, a customer's address, an
access token, or a password that some site put in a GET parameter.

That would matter less if titles stayed on disk, but they do not: they reach
card copy ("you were last in *<title>*"), which is stored rendered in the
``recommendations`` table and printed verbatim into exportable reports. A report
is a file the user emails to a supervisor. So the redaction happens here, at the
boundary where a title first enters a feature context, rather than at each of
the places one is rendered — there are several of those and there will be more,
and a privacy control that has to be remembered at every call site is one that
will eventually be forgotten.

The bias is deliberately towards keeping titles readable. Replacing everything
with ``<redacted>`` protects perfectly and destroys the feature: "resume what
you were doing" is useless if it cannot name the thing. So the rule is to strip
*identifiers* and keep *nouns* — drop the query string, keep the site; drop the
directory, keep the file name; drop the token, keep the sentence around it.

This reduces exposure. It is not a guarantee, and the docstrings say so: a title
reading "Q3 layoffs - Acme Corp - Google Docs" contains nothing this module can
recognise as sensitive and will pass through untouched. The honest claim is
"structured secrets are removed", not "titles are safe".
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("smartdesk.recommendations.redaction")

#: Longest title kept. Past this the tail is almost always breadcrumbs, and a
#: long title in a card reads badly anyway.
MAX_LENGTH = 80

#: Anything that looks like a credential rather than a word.
#:
#: Twenty or more characters with no vowel-and-space structure is not prose. It
#: catches hex digests, base64 blobs, JWT segments and API keys, which is most
#: of what leaks through a URL.
_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_\-]{20,})[A-Za-z0-9_\-]*\d[A-Za-z0-9_\-]*\b")

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

#: A host: a dotted domain with a TLD, ``localhost``, or a dotted quad.
#:
#: Specific on purpose, because the schemeless form below leans on it. A
#: pattern loose enough to match any word would read "Report 19/08/2026" as a
#: host followed by a path, and eat the date.
_HOST = (
    r"(?:(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
    r"|localhost"
    r"|(?:\d{1,3}\.){3}\d{1,3})"
)

#: A URL, captured so the host can be kept and the rest dropped.
#:
#: Two forms, because titles carry both. The schemed one is what a pasted link
#: looks like. The schemeless one is what an address bar and most dev tooling
#: actually show — ``localhost:8000/admin?token=...`` — since browsers hide
#: the ``https://``. Requiring the scheme meant that second form passed through
#: whole, query string included, which is the exact case this module exists for.
#:
#: The schemeless branch only fires when there is a path, query or fragment to
#: strip. A bare host is already the noun the sweep would reduce it to, and
#: matching it would only rewrite "example.com" to itself.
_URL = re.compile(
    r"https?://(?P<schemed>[^\s/?#]+)[^\s]*"
    r"|\b(?P<bare>" + _HOST + r"(?::\d+)?)[/?#][^\s]*",
    re.IGNORECASE,
)

#: Words that name a credential, matched as a delimited component of a key.
#:
#: Delimited rather than searched as a substring: "monkey" contains "key", and
#: redacting ``monkey=jim`` would be a false positive on an ordinary title.
#: Requiring a non-letter on either side still catches ``AWS_SECRET_ACCESS_KEY``,
#: ``access_token`` and ``api-key``, which is how these are really spelled.
_SECRET_WORD = (
    r"(?:passwords?|passwd|pwd|secrets?|tokens?|apikey|key|auth"
    r"|credentials?|session|signature)"
)

#: ``password=hunter2`` — a short secret with its own name written beside it.
#:
#: :data:`_TOKEN` only fires at twenty characters, on the reasoning that
#: anything shorter is prose. That is true of prose and false of passwords, so
#: every short credential went straight through it. Here the *key* is the
#: signal rather than the length of the value, which is the only thing that
#: makes a seven-character password recognisable at all.
#:
#: Only ``=``, never ``:``. Colons are ordinary punctuation in a title — "Key:
#: Largo", "Re: budget" — and accepting them would redact the words after any
#: of those. An assignment that leaks a credential is written with ``=``: it is
#: what a query parameter and an environment variable both use.
_SECRET_ASSIGNMENT = re.compile(
    r"\b(?P<key>[A-Za-z0-9_-]*(?<![A-Za-z])" + _SECRET_WORD + r"(?![A-Za-z])"
    r"[A-Za-z0-9_-]*\s*=\s*)(?P<value>[^\s&;]+)",
    re.IGNORECASE,
)

#: Windows (``C:\a\b\c.txt``) and POSIX (``/home/a/b.txt``) absolute paths.
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s]+\\)*([^\\\s]*)")
_POSIX_PATH = re.compile(r"(?<![\w.])/(?:[^/\s]+/)+([^/\s]*)")

#: Bare numbers long enough to be an account, card, phone or ID.
_LONG_NUMBER = re.compile(r"\b\d{7,}\b")

#: The same identifiers written in groups, which is how people actually write
#: them: "4111 1111 1111 1111", "812 3456 7890", "555-123-4567". Grouping is
#: precisely what defeats :data:`_LONG_NUMBER` — a sixteen-digit card split
#: into fours contains no run of seven, so a pattern looking for one sees
#: nothing to redact.
#:
#: Matched loosely and filtered in :func:`_redact_grouped`, because the shape
#: is shared with things that must survive. A date is the important one:
#: "2026-08-19" is three groups totalling eight digits and is not an
#: identifier, so a rule counting digits alone would strip every date out of
#: every title.
_GROUPED_NUMBER = re.compile(r"\b\d{2,}(?:[ -]\d{2,})+\b")

#: Dates, in the orders a window title actually uses. Excluded from the
#: grouped-number sweep above rather than from redaction generally.
_DATE_LIKE = re.compile(
    r"\A(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\Z"
)

#: Digits a grouped run must total before it is treated as an identifier.
#: Seven matches :data:`_LONG_NUMBER`, and is the point below which a run is
#: more likely a version, a score or a time range than an account number.
_IDENTIFIER_DIGITS = 7


def _redact_url(match: re.Match) -> str:
    """Keep whichever host branch matched, drop everything after it."""
    return match.group("schemed") or match.group("bare")


def _redact_grouped(match: re.Match) -> str:
    """Redact a grouped digit run unless it is a date or too short to identify."""
    text = match.group(0)
    if _DATE_LIKE.match(text):
        return text
    if sum(char.isdigit() for char in text) < _IDENTIFIER_DIGITS:
        return text
    return "<number>"


def redact_title(title: str | None, max_length: int = MAX_LENGTH) -> str:
    """Strip structured identifiers from a title, keeping it readable.

    Applied in a fixed order, because the patterns overlap and the order
    decides which one wins. Emails go first, since an address inside a URL
    should be removed as an address rather than surviving as part of a host.
    Paths go before the token sweep, so a directory full of hex-named folders
    collapses to its file name instead of a row of ``<token>``.

    Empty or missing input returns ``""`` rather than a placeholder: the callers
    already treat an empty title as "no title", and inventing one would put
    ``<redacted>`` in a card where nothing was recorded at all.
    """
    if not title:
        return ""

    cleaned = str(title)
    cleaned = _EMAIL.sub("<email>", cleaned)
    # Before the URL sweep, not after. A credential in a query string is
    # usually carried off with the rest of the query, but not when the URL
    # was written without its scheme, and not when the assignment is loose
    # in a terminal title with no URL around it at all. Neutralising it here
    # means neither pattern has to be the one that works.
    cleaned = _SECRET_ASSIGNMENT.sub(r"\g<key><token>", cleaned)
    # Keep the host so "GitHub" survives; drop path and query, which is where
    # tokens, document ids and search terms live.
    cleaned = _URL.sub(_redact_url, cleaned)
    cleaned = _WINDOWS_PATH.sub(lambda m: m.group(1) or "<path>", cleaned)
    cleaned = _POSIX_PATH.sub(lambda m: m.group(1) or "<path>", cleaned)
    cleaned = _TOKEN.sub("<token>", cleaned)
    cleaned = _LONG_NUMBER.sub("<number>", cleaned)
    cleaned = _GROUPED_NUMBER.sub(_redact_grouped, cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\u2014|\t")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "..."
    return cleaned


def redact_features(data: dict, keys: tuple[str, ...]) -> None:
    """Redact the named title features in place.

    In place because the feature builders assemble one dict incrementally and
    returning a copy would mean every caller remembering to use it — the same
    failure this module exists to avoid.
    """
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            data[key] = redact_title(value)


#: Every feature that carries free text from outside the application.
#:
#: Kept as one list so a new title feature is one edit away from being covered,
#: and so a test can assert that the list and the builders agree.
TITLE_FEATURES = (
    "meeting_title",
    "next_meeting_title",
    "current_title",
    "last_work_title",
    "repeat_context_title",
    "peak_clash_title",
)


# --------------------------------------------------------------------- #
# Backfill
# --------------------------------------------------------------------- #

def backfill_stored_cards(
    db,
    user_id: str | None = None,
    limit: int | None = None,
) -> dict:
    """Scrub titles out of cards that were stored before redaction existed.

    Redacting at the feature boundary protects everything written from now on
    and nothing written before it. Those older rows are the ones that matter
    most for a report: they hold rendered copy, they are what an export quotes,
    and a card from six months ago is exactly the one nobody remembers the
    contents of.

    The rendered sentence is patched rather than re-rendered. Storing copy
    rather than regenerating it is a deliberate property of this engine — a
    card the user saw yesterday still says what it said yesterday, even after a
    template is reworded — and re-rendering would quietly rewrite history to
    today's wording. So the raw fact is redacted, and every occurrence of the
    old value inside ``title``, ``why`` and ``action`` is replaced with the
    scrubbed one. The sentence keeps its shape; only the sensitive substring
    changes.

    Idempotent: a second run finds nothing to do, because ``redact_title`` is
    itself idempotent and the replaced values no longer match.

    Returns counts rather than the changed rows. The point of the operation is
    that the values should not be moved around more than necessary.
    """
    from app.models.db import RecommendationRecord

    query = db.query(RecommendationRecord)
    if user_id:
        query = query.filter(RecommendationRecord.user_id == user_id)
    if limit:
        query = query.limit(limit)

    scanned = changed = fields_changed = 0
    for record in query.all():
        scanned += 1
        try:
            facts = json.loads(record.facts_json) if record.facts_json else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(facts, dict):
            continue

        replacements: list[tuple[str, str]] = []
        for key in TITLE_FEATURES:
            raw = facts.get(key)
            if not isinstance(raw, str) or not raw:
                continue
            clean = redact_title(raw)
            if clean != raw:
                facts[key] = clean
                replacements.append((raw, clean))

        if not replacements:
            continue

        # Longest first: one title can be a substring of another, and replacing
        # the shorter one first would corrupt the longer.
        replacements.sort(key=lambda pair: -len(pair[0]))
        touched = False
        for field in ("title", "why", "action"):
            text = getattr(record, field, None)
            if not isinstance(text, str):
                continue
            updated = text
            for raw, clean in replacements:
                updated = updated.replace(raw, clean)
            if updated != text:
                setattr(record, field, updated)
                fields_changed += 1
                touched = True

        record.facts_json = json.dumps(facts, ensure_ascii=False)
        changed += 1
        if touched:
            logger.debug("Redacted stored card %s", record.id)

    if changed:
        db.commit()
    logger.info(
        "Redaction backfill: %d card(s) scanned, %d rewritten, %d rendered "
        "field(s) changed", scanned, changed, fields_changed,
    )
    return {
        "scanned": scanned,
        "cards_rewritten": changed,
        "rendered_fields_changed": fields_changed,
    }
