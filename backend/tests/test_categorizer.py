"""Tests for activity categorization, centred on the browser-chrome failure.

The bug these guard against: the zero-shot embedding classifier reported
``(cosine + 1) / 2`` as confidence, which no threshold could reject, so it
returned its nearest label for every segment. Browser window titles are short
strings of product nouns and so is the label text for meetings, so meetings
collected 3,797 Comet segments — 36% of all recorded active time.
"""

from __future__ import annotations

import pytest

from app.models.db import ActivitySegmentRecord
from app.services.categorizer import categorizer


def segment(app_name=None, title=None, detail=None, state="active") -> ActivitySegmentRecord:
    return ActivitySegmentRecord(
        app_name=app_name,
        title=title,
        detail=detail,
        state=state,
        primary_source="os",
    )


# --------------------------------------------------------------------------- #
# Title normalisation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Point Estimation - MoM and MLE - YouTube - Comet", "Point Estimation - MoM and MLE"),
        ("handout10.pdf - Comet", "handout10.pdf"),
        ("Inbox (12) - Gmail - Google Chrome", "Inbox (12)"),
        ("my notes and 3 more pages - Personal - Microsoft\u200b Edge", "my notes"),
        ("Prolog Exam Lab - Google Chrome", "Prolog Exam Lab"),
        # A title that is only the site name describes the tab, not the work.
        ("Google Gemini - Comet", ""),
        ("Claude - Comet", ""),
        (None, ""),
    ],
)
def test_clean_title_strips_boilerplate(raw, expected):
    assert categorizer.clean_title(raw) == expected


@pytest.mark.parametrize(
    "title", ["Search", "Extensions - Comet", "Untitled - Comet", "New Tab", "Save As"]
)
def test_chrome_titles_recognised(title):
    assert categorizer.is_chrome_title(title)


@pytest.mark.parametrize("title", ["handout10.pdf - Comet", "Prolog Exam Lab", "Google Gemini"])
def test_content_titles_are_not_chrome(title):
    assert not categorizer.is_chrome_title(title)


def test_build_text_drops_known_hosts_but_keeps_unknown_ones():
    """A recognised host is already handled by the rules; repeating it in the
    embedding text only pulls the vector toward the site and away from the topic."""
    known = segment(
        app_name="comet",
        title="Hypothesis Testing Solutions - Google Gemini - Comet",
        detail="https://gemini.google.com/app/x",
    )
    assert categorizer.build_text(known) == "Hypothesis Testing Solutions"

    unknown = segment(
        app_name="comet", title="Rise Up Mora - Comet", detail="https://www.riseupmora.lk/x"
    )
    assert categorizer.build_text(unknown) == "Rise Up Mora riseupmora.lk"


# --------------------------------------------------------------------------- #
# The regression itself
# --------------------------------------------------------------------------- #
BROWSER_CHROME = [
    ("comet", "Search", None),
    ("comet", "Extensions - Comet", None),
    ("comet", "Untitled - Comet", "http://www.msftconnecttest.com/redirect"),
    ("comet", "Web Authentication - Comet", "https://wlan.uom.lk/login.html?redirect=x"),
    ("comet", "New Tab - Comet", None),
    ("SnippingTool", "Snipping Tool Overlay", None),
]


@pytest.mark.parametrize("app_name, title, detail", BROWSER_CHROME)
def test_browser_chrome_is_never_a_meeting(app_name, title, detail):
    category, _method, _confidence = categorizer.predict(
        segment(app_name=app_name, title=title, detail=detail)
    )
    assert category != "meetings"


@pytest.mark.parametrize("app_name, title, detail", BROWSER_CHROME)
def test_browser_chrome_is_never_decided_by_embedding(app_name, title, detail):
    """These titles carry no topic. The embedding classifier cannot answer
    "I don't know", so it must not be asked."""
    _category, method, _confidence = categorizer.predict(
        segment(app_name=app_name, title=title, detail=detail)
    )
    assert method != "embedding"


@pytest.mark.parametrize(
    "app_name, title, detail",
    [
        ("comet", "handout10.pdf - Comet", "https://online.uom.lk/pluginfile.php/1/h.pdf"),
        ("comet", "Google Gemini - Comet", "https://gemini.google.com/app"),
        ("comet", "org/smartdesk at FocusScore - Comet", "https://github.com/org/smartdesk"),
        ("comet", "Collection Health - Comet", "http://127.0.0.1:8000/dashboard"),
        ("vlc", "Inception (2010) 1080p BRRip x265.mkv - VLC media player", None),
        ("comet", "Papers - Google Drive - Comet", "https://drive.google.com/drive/x"),
    ],
)
def test_real_browsing_is_not_a_meeting(app_name, title, detail):
    category, _method, _confidence = categorizer.predict(
        segment(app_name=app_name, title=title, detail=detail)
    )
    assert category != "meetings"


# --------------------------------------------------------------------------- #
# Meetings now require evidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "app_name, title, detail",
    [
        ("zoom", "Zoom Meeting", None),
        ("Teams", "Daily standup | Microsoft Teams", None),
        ("comet", "Weekly sync - Google Meet - Comet", "https://meet.google.com/abc-defg-hij"),
        ("comet", "Sprint review - Comet", "https://us05web.zoom.us/j/123"),
    ],
)
def test_conferencing_evidence_yields_meetings(app_name, title, detail):
    category, method, confidence = categorizer.predict(
        segment(app_name=app_name, title=title, detail=detail)
    )
    assert category == "meetings"
    assert method == "rule"
    assert confidence >= 0.8


def test_a_page_about_meetings_is_not_a_meeting():
    """Talking about meetings is not attending one."""
    category, _method, _confidence = categorizer.predict(
        segment(
            app_name="comet",
            title="Meeting notes template - Notion - Comet",
            detail="https://www.notion.so/x",
        )
    )
    assert category != "meetings"


def test_meetings_is_unreachable_from_the_embedding_classifier():
    assert "meetings" in categorizer.EMBEDDING_EXCLUDED_LABELS
    scores = categorizer.score_labels(categorizer._label_embeddings["meetings"])
    assert "meetings" not in scores


# --------------------------------------------------------------------------- #
# Host rules
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "detail, expected",
    [
        # An unknown host serving Moodle URLs is some university's own LMS.
        ("https://online.uom.lk/pluginfile.php/10528/mod_resource/x.pdf", "learn"),
        ("https://lms.example.edu/course/view.php?id=7", "learn"),
        ("http://www.msftconnecttest.com/redirect", "system"),
        ("https://accounts.google.com/signin", "system"),
        ("https://github.com/org/repo", "work"),
        ("https://www.figma.com/make/x", "work"),
        ("https://www.linkedin.com/feed/", "social_media"),
        ("http://localhost:5179/", "work"),
        ("http://127.0.0.1:8000/dashboard", "work"),
    ],
)
def test_decisive_hosts(detail, expected):
    seg = segment(app_name="comet", title="Some page - Comet", detail=detail)
    category, tier, _confidence = categorizer.categorize_by_host(seg)
    assert (category, tier) == (expected, "decisive")


def test_subdomains_match_their_parent_host():
    seg = segment(app_name="comet", title="Docs - Comet", detail="https://docs.github.com/en")
    assert categorizer.categorize_by_host(seg)[0] == "work"


def test_unknown_host_yields_nothing():
    seg = segment(app_name="comet", title="x - Comet", detail="https://example.invalid/a")
    assert categorizer.categorize_by_host(seg) == (None, None, 0.0)


def test_non_url_detail_is_not_parsed_as_a_host():
    seg = segment(app_name="Code", title="main.py", detail="C:/projects/smartdesk/main.py")
    assert categorizer.categorize_by_host(seg) == (None, None, 0.0)


# --------------------------------------------------------------------------- #
# Keyword matching
# --------------------------------------------------------------------------- #
def test_keywords_match_on_word_boundaries():
    """The social_media keyword "x" used to match as a bare substring, so every
    title containing the letter — "x265", "Excel", "next" — scored for it."""
    category, _confidence = categorizer.categorize_by_rules(
        "Inception 1080p BRRip HEVC x265.mkv", None, "vlc"
    )
    assert category != "social_media"

    category, _confidence = categorizer.categorize_by_rules("Budget.xlsx - Excel", None, "excel")
    assert category != "social_media"


def test_unstorable_category_is_mapped_not_discarded():
    """"documentation" is a real prediction the schema has never accepted.
    Dropping it loses a correct answer over a naming mismatch."""
    assert "documentation" not in categorizer.PERSISTABLE_CATEGORIES
    assert categorizer.CATEGORY_ALIASES["documentation"] == "work"


def test_every_prediction_is_storable():
    """A category the CHECK constraint rejects fails the INSERT, and segments
    are persisted per batch — one bad row discards the whole build window."""
    cases = BROWSER_CHROME + [
        ("comet", "handout10.pdf - Comet", "https://online.uom.lk/pluginfile.php/1/h.pdf"),
        ("zoom", "Zoom Meeting", None),
        ("Code", "categorizer.py - smartdesk - Visual Studio Code", None),
        ("comet", "README - Comet", "https://github.com/org/repo"),
        (None, None, None),
    ]
    for app_name, title, detail in cases:
        category, method, confidence = categorizer.predict(
            segment(app_name=app_name, title=title, detail=detail)
        )
        assert category is None or category in categorizer.PERSISTABLE_CATEGORIES
        assert method in (None, "rule", "embedding", "supervised")
        assert confidence is None or 0.0 <= confidence <= 1.0
