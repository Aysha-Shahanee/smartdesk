"""Activity categorization service.

Implements rule-based, supervised learning, and embedding-based categorization
of activity segments into predefined categories: work, learn, communication,
entertainment, social_media, system, meetings, other.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple, Any
from urllib.parse import urlparse

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import LabelEncoder

from app.models.db import ActivitySegmentRecord, ActivitySegmentLabelRecord
from app.services.embedder import embedder
from app.core.database import SessionLocal

logger = logging.getLogger("smartdesk.categorizer")


class Categorizer:
    """Service for categorizing activity segments."""

    # Categories the database will actually accept, mirroring
    # ck_activity_segments_category. CATEGORY_KEYWORDS and LABEL_TEXTS carry an
    # extra "documentation" label that the schema has never allowed, so any
    # segment scoring highest on it made the INSERT fail — and because segments
    # are persisted in one batch, a single such row discarded every segment in
    # that build window. Predictions are filtered to this set so a taxonomy that
    # drifts ahead of the schema degrades one label instead of losing the batch.
    PERSISTABLE_CATEGORIES = frozenset({
        "work",
        "learn",
        "communication",
        "entertainment",
        "social_media",
        "system",
        "meetings",
        "other",
    })

    # Where a category the schema does not list should land instead. Dropping
    # the prediction outright, as the guard above used to do unconditionally,
    # throws away a correct answer over a naming mismatch: "documentation" is
    # a kind of work, and 31 segments in the meetings repair alone came back
    # uncategorised for want of that one line.
    CATEGORY_ALIASES = {
        "documentation": "work",
    }

    # Category keywords for rule-based classification
    CATEGORY_KEYWORDS = {
        "work": [
            "meeting",
            "call",
            "email",
            "document",
            "spreadsheet",
            "presentation",
            "report",
            "project",
            "task",
            "deadline",
            "conference",
            "zoom",
            "teams",
            "slack",
            "outlook",
            "word",
            "excel",
            "powerpoint",
            "notion",
            "asana",
            "trello",
            "jira",
            "confluence",
            "github",
            "gitlab",
            "bitbucket",
            "docker",
            "kubernetes",
            "aws",
            "azure",
            "gcp",
            "linux",
            "windows",
            "terminal",
            "console",
            "command",
            "admin",
            "readme",
            "readme.md",
            "ppt",
            "pptx",
            "pdf",
            "slide",
            "slideshow",
            ".py",
            ".js",
            ".ts",
            ".java",
            ".cs",
            ".go",
            ".rs",
            ".cpp",
            ".c",
            ".h",
            "visual studio",
            "vscode",
            "code",
            "idea",
            "pycharm",
            "intellij",
            "sublime",
            "vim",
            "emacs",
            "terminal",
            "console",
        ],
        "learn": [
            # Coursework vocabulary and LMS names. A page titled "Log in to the
            # site | LMS" or "Prolog Exam Lab" is unmistakably study, but says
            # so in words no other keyword list contained, so it reached the
            # embedding classifier with nothing to match on and came back
            # uncategorised.
            "lms",
            "moodle",
            "blackboard",
            "canvas",
            "exam",
            "quiz",
            "assignment",
            "homework",
            "tute",
            "past paper",
            "syllabus",
            "coursework",
            "semester",
            "learn",
            "study",
            "tutorial",
            "course",
            "lecture",
            "documentation",
            "docs",
            "training",
            "education",
            "school",
            "university",
            "bootcamp",
            "guide",
            "how to",
            "lesson",
            "training",
            "education",
            "academy",
            "class",
            "lesson",
            "training",
        ],
        "communication": [
            "chat",
            "message",
            "email",
            "call",
            "meeting",
            "discussion",
            "conversation",
            "teams",
            "slack",
            "discord",
            "whatsapp",
            "signal",
            "telegram",
            "zoom",
            "skype",
            "meet",
            "hangout",
            "outlook",
            "gmail",
            "mail",
            "message",
            "chat",
            "conversation",
            "discussion",
            "talk",
            "call",
            "video call",
            "voice call",
        ],
        "entertainment": [
            # Desktop media players: a film in VLC has no URL and no keyword
            # in its title but the container extension, so without these a
            # two-hour movie fell through to whatever the embedding guessed.
            "vlc",
            "media player",
            "potplayer",
            "mpc-hc",
            "mpv",
            "quicktime",
            ".mkv",
            ".mp4",
            ".avi",
            ".mov",
            "youtube",
            "netflix",
            "hulu",
            "disney+",
            "prime video",
            "hbo",
            "twitch",
            "spotify",
            "pandora",
            "soundcloud",
            "music",
            "video",
            "movie",
            "film",
            "show",
            "series",
            "game",
            "gaming",
            "steam",
            "epic",
            "origin",
            "ubisoft",
            "riot",
            "blizzard",
            "nintendo",
            "playstation",
            "xbox",
            "twitch",
            "youtube",
            "tiktok",
            "instagram",
            "facebook",
            "twitter",
            "reddit",
        ],
        "social_media": [
            "facebook",
            "twitter",
            "instagram",
            "tiktok",
            "snapchat",
            "linkedin",
            "pinterest",
            "reddit",
            "discord",
            "whatsapp",
            "telegram",
            "signal",
            "wechat",
            "weibo",
            "qq",
            "twitter",
            "x",
            "threads",
            "mastodon",
            "bluesky",
            "social",
            "feed",
            "timeline",
            "story",
            "post",
            "share",
            "like",
            "comment",
            "follow",
            "friend",
            "network",
        ],
        "system": [
            "settings",
            "control panel",
            "system preferences",
            "task manager",
            "activity monitor",
            "finder",
            "explorer",
            "files",
            "file manager",
            "registry",
            "control panel",
            "system",
            "settings",
            "preferences",
            "control",
            "admin",
            "administrator",
            "cmd",
            "powershell",
            "terminal",
            "command prompt",
            "bash",
            "zsh",
            "shell",
            "console",
            "update",
            "upgrade",
            "install",
            "installer",
            "setup",
            "configuration",
            "config",
            "driver",
            "antivirus",
            "firewall",
            "security",
            "defender",
            "backup",
            "recovery",
            "maintenance",
            "database",
            "sqlite",
            "db browser",
            "sqlitebrowser",
            "sqlite studio",
            "sqlite expert",
        ],
        "meetings": [
            "meeting",
            "call",
            "conference",
            "zoom",
            "teams",
            "meet",
            "hangout",
            "webex",
            "goto",
            "webinar",
            "conference call",
            "video conference",
            "video call",
            "audio call",
            "standup",
            "stand-up",
            "daily standup",
            "sprint planning",
            "retrospective",
            "retro",
            "planning",
            "review",
            "demo",
            "presentation",
            "pitch",
            "interview",
            "one on one",
            "1:1",
            "check-in",
            "checkin",
        ],
        "documentation": [
            "word",
            "google docs",
            "docs",
            "notion",
            "confluence",
            "markdown",
            "readme",
            "wiki",
            "documentation",
            "guide",
            "manual",
            "faq",
            "help",
            "pdf",
            "doc",
            "docx",
            "odt",
            "rtf",
            "tex",
            "latex",
            "xmind",
            "mindmap",
            "drawio",
            "visio",
            "excel",
            "xls",
            "xlsx",
            "csv",
            "tsv",
            "json",
            "yaml",
            "xml",
            "html",
            "htm",
            "svg",
            "diagram",
            "flowchart",
            "uml",
            "eral",
            "reference",
            "tutorial",
            "how-to",
        ],
        "other": [],  # catch‑all
    }

    # Label texts used for embedding‑based zero‑shot classification.
    # These are short descriptive phrases that capture the essence of each category.
    LABEL_TEXTS: Dict[str, str] = {
        "work": "productive work activity, coding, office tasks, meetings, email, programming, development, debugging, documentation, readme, guide, manual",
        "learn": "studying, tutorials, online courses, documentation, research, lectures, lessons, education, training, courses, how-to",
        "meetings": "google meet, teams, zoom, webex, video conference, conference call, meeting",
        "communication": "chat, messaging, video calls, phone calls, collaboration, slack, discord, whatsapp, signals",
        "entertainment": "movies, music, gaming, streaming, videos for fun, youtube music, youtube gaming, youtube live stream, netflix, hulu, disney+, spotify, podcast",
        "social_media": "browsing Facebook, Twitter, Instagram, Reddit, TikTok, social networks, feeds, likes, shares",
        "system": "system settings, file explorer, control panel, terminal, updates, drivers, registry, task manager",
        "other": "miscellaneous activity not covered above",
        "documentation": "documentation, user guide, reference manual, help file, readme, wiki, knowledge base, FAQ, tutorial, how‑to, whitepaper, spec, design doc, architecture doc, API doc, man page",
    }

    # Labels the zero-shot embedding classifier is not allowed to choose.
    # "meetings" is anchored entirely in proper nouns — Zoom, Teams, Meet,
    # Webex — so its label text embeds like any other short list of product
    # names, and browser window titles are short lists of product names
    # ("Google Gemini - Comet", "Untitled - Comet"). It won the argmax on
    # 3,797 Comet segments, at cosine similarities around 0.28, purely on that
    # surface resemblance. A meeting is knowable from hard evidence instead:
    # the conferencing app is in the foreground, or its URL is open. See
    # :meth:`_meeting_evidence` — that is now the only route to this label.
    EMBEDDING_EXCLUDED_LABELS = frozenset({"meetings"})

    # ------------------------------------------------------------------ #
    # Browser chrome normalisation
    # ------------------------------------------------------------------ #
    BROWSER_APPS = frozenset({
        "comet", "chrome", "google chrome", "chromium", "msedge",
        "microsoft edge", "firefox", "brave", "opera", "opera gx", "vivaldi",
        "safari", "arc", "zen",
    })

    # A browser reports its window title as "<page title> - <Browser>". The
    # browser name is on every row from that app, so it carries no signal about
    # what the user was doing, but it does drag every such segment into the same
    # small region of embedding space — where whichever label text happens to be
    # nearest collects all of them. Strip it before embedding.
    _BROWSER_SUFFIX_RE = re.compile(
        r"(?:\s+and\s+\d+\s+more\s+(?:pages?|tabs?))?"          # Edge tab groups
        r"(?:\s*[-–—]\s*(?:Personal|Work|Profile\s*\d*))?"      # Edge profiles
        r"\s*[-–—]\s*(?:"
        r"Comet|Google\s+Chrome|Chromium|Chrome|Mozilla\s+Firefox|Firefox|"
        r"Microsoft\s+Edge|Edge|Brave(?:\s+Browser)?|Opera(?:\s+GX)?|Vivaldi|"
        r"Safari|Arc|Zen(?:\s+Browser)?"
        r")\s*$",
        re.IGNORECASE,
    )

    # Site names browsers append after the page title ("<topic> - Google
    # Gemini - Comet"). Removed for the same reason as the browser name: the
    # topic is the signal, the site name is boilerplate repeated across every
    # visit. "Google Gemini" in particular sits a hair from "google meet" in
    # both spelling and embedding space, and gemini.google.com alone accounted
    # for 692 of the mislabelled segments.
    SITE_SUFFIXES = frozenset({
        "google gemini", "gemini", "claude", "chatgpt", "openai", "copilot",
        "perplexity", "youtube", "google drive", "google docs", "google sheets",
        "google slides", "gmail", "github", "gitlab", "figma", "notion",
        "stack overflow", "linkedin", "x", "twitter", "facebook", "reddit",
        "wikipedia", "kaggle", "medium",
    })

    # Titles naming the browser's or the OS's own furniture rather than
    # anything the user chose to look at. There is no topic to classify here,
    # so these must never reach the embedding classifier: it cannot return
    # "nothing", only its nearest label.
    CHROME_TITLES = frozenset({
        "new tab", "new incognito tab", "new private tab", "untitled",
        "search", "extensions", "settings", "preferences", "downloads",
        "history", "bookmarks", "bookmark manager", "profiles", "about:blank",
        "blank page", "save as", "save file", "save image", "open", "open file",
        "select folder", "choose file", "print", "sign in", "log in",
        "privacy and security", "web authentication", "web authentication redirect",
        "snipping tool overlay", "task switching", "program manager",
        "windows input experience", "start", "cortana", "search results",
    })

    # ------------------------------------------------------------------ #
    # Host rules
    # ------------------------------------------------------------------ #
    # For a browser segment the URL host is a far stronger and more stable
    # signal than an embedding of the window title, and it is cheap. Matched by
    # exact host or dotted suffix, so "docs.github.com" matches "github.com".
    #
    # DECISIVE: the host settles the category whatever the page title says —
    # a LinkedIn page is social media even when the post is about work.
    DECISIVE_HOSTS: Tuple[Tuple[str, str], ...] = (
        # Connectivity probes and captive portals. The OS opened these, not
        # the user; crediting them to any real activity is a fabrication.
        ("msftconnecttest.com", "system"),
        ("connectivitycheck.gstatic.com", "system"),
        ("connectivitycheck.android.com", "system"),
        ("captive.apple.com", "system"),
        ("detectportal.firefox.com", "system"),
        ("accounts.google.com", "system"),
        ("login.microsoftonline.com", "system"),
        # Social.
        ("facebook.com", "social_media"),
        ("instagram.com", "social_media"),
        ("twitter.com", "social_media"),
        ("x.com", "social_media"),
        ("linkedin.com", "social_media"),
        ("reddit.com", "social_media"),
        ("tiktok.com", "social_media"),
        ("pinterest.com", "social_media"),
        ("threads.net", "social_media"),
        # Entertainment.
        ("netflix.com", "entertainment"),
        ("primevideo.com", "entertainment"),
        ("hulu.com", "entertainment"),
        ("disneyplus.com", "entertainment"),
        ("twitch.tv", "entertainment"),
        ("spotify.com", "entertainment"),
        ("soundcloud.com", "entertainment"),
        ("subtitlecat.com", "entertainment"),
        ("opensubtitles.org", "entertainment"),
        # Learning platforms.
        ("moodle.org", "learn"),
        ("moodlecloud.com", "learn"),
        ("instructure.com", "learn"),
        ("blackboard.com", "learn"),
        ("coursera.org", "learn"),
        ("edx.org", "learn"),
        ("udemy.com", "learn"),
        ("khanacademy.org", "learn"),
        ("w3schools.com", "learn"),
        ("geeksforgeeks.org", "learn"),
        ("brilliant.org", "learn"),
        ("kaggle.com", "learn"),
        # Work.
        ("github.com", "work"),
        ("gitlab.com", "work"),
        ("bitbucket.org", "work"),
        ("stackoverflow.com", "work"),
        ("figma.com", "work"),
        ("atlassian.net", "work"),
        ("jira.com", "work"),
        ("notion.so", "work"),
        ("trello.com", "work"),
        ("asana.com", "work"),
        ("overleaf.com", "work"),
        # Communication.
        ("mail.google.com", "communication"),
        ("outlook.office.com", "communication"),
        ("outlook.live.com", "communication"),
        ("web.whatsapp.com", "communication"),
        ("discord.com", "communication"),
        ("slack.com", "communication"),
    )

    # FALLBACK: the host says what the site is, but the page title carries the
    # topic. Used only when the title has no content of its own, or when the
    # embedding classifier is not confident enough to overrule it.
    FALLBACK_HOSTS: Tuple[Tuple[str, str], ...] = (
        ("gemini.google.com", "work"),
        ("claude.ai", "work"),
        ("chatgpt.com", "work"),
        ("chat.openai.com", "work"),
        ("copilot.microsoft.com", "work"),
        ("perplexity.ai", "work"),
        ("drive.google.com", "work"),
        ("docs.google.com", "work"),
        ("sheets.google.com", "work"),
        ("google.com", "other"),
        ("duckduckgo.com", "other"),
        ("bing.com", "other"),
    )

    # A locally served page is something the user is building or running.
    _LOCAL_HOST_RE = re.compile(
        r"^(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|192\.168\.\d+\.\d+|"
        r"10\.\d+\.\d+\.\d+)(?::\d+)?$"
    )

    # Moodle's URL layout, which identifies a learning-management system on a
    # host this table will never have heard of — every university self-hosts
    # under its own domain (here, online.uom.lk: 1,870 of the mislabelled
    # segments and 25 hours of study filed as meetings).
    _LMS_PATH_RE = re.compile(
        r"/(?:pluginfile\.php|course/view\.php|mod/[a-z]+/view\.php|"
        r"mod/(?:resource|assign|quiz|forum|folder)/|my/courses|"
        r"courses/\d+/(?:assignments|modules|files)|webapps/blackboard)",
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------ #
    # Meeting evidence
    # ------------------------------------------------------------------ #
    # The only routes to the "meetings" label. Each is a positive observation
    # that a conferencing tool was in the foreground, not a resemblance.
    MEETING_APPS = frozenset({
        "zoom", "zoom.us", "cpthost", "teams", "ms-teams", "msteams",
        "microsoft teams", "webex", "webexmta", "gotomeeting", "bluejeans",
        "skype", "whereby", "jitsi", "chime", "ringcentral", "lifesize",
    })
    MEETING_HOSTS: Tuple[str, ...] = (
        "meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com",
        "webex.com", "gotomeeting.com", "gotomeet.me", "whereby.com",
        "meet.jit.si", "bluejeans.com", "chime.aws", "around.co",
    )
    # Titles conferencing clients set on their own windows. Anchored so that a
    # page *about* meetings ("Meeting notes - Notion") does not match.
    _MEETING_TITLE_RE = re.compile(
        r"^(?:zoom\s+(?:meeting|webinar)|meeting\s+with\b|"
        r".*\|\s*microsoft\s+teams$|.*\bgoogle\s+meet$|"
        r".*\bwebex(?:\s+meeting)?$)",
        re.IGNORECASE,
    )

    # YouTube‑specific heuristic boosts (applied after similarity scoring)
    _YT_LEARN_KEYWORDS = re.compile(
        r"\b(lecture|tutorial|course|lesson|education|training|how\s+to|explained|review|talk|conference|webinar)\b",
        re.I,
    )
    _YT_ENTERTAINMENT_KEYWORDS = re.compile(
        r"\b(music|song|gaming|live\s+stream|stream|lets\s+play|playthrough|review|unboxing|haul|vlog|comedy|funny|funny|challenge|prank)\b",
        re.I,
    )

    def __init__(self) -> None:
        """Initialize the categorizer."""
        # Pre‑compute keyword weights for rule‑based classification
        # Keywords are matched on word boundaries rather than as bare
        # substrings. As substrings the social_media entry "x" matched every
        # title containing the letter — "x265", "Excel", "next" — and "post",
        # "like" and "demo" matched inside "composite", "likely" and
        # "democracy", so the rule scorer awarded points on spelling
        # accidents. Boundaries are only added on the sides where the keyword
        # starts or ends with a word character, keeping ".py" and "disney+"
        # matchable.
        self._category_weights: Dict[str, Dict[str, float]] = {}
        self._keyword_patterns: Dict[str, re.Pattern[str]] = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            weights: Dict[str, float] = {}
            for keyword in keywords:
                key = keyword.lower()
                # Longer phrases get higher weight
                weights[key] = len(keyword.split()) * 0.5 + 1
                if key not in self._keyword_patterns:
                    pattern = re.escape(key)
                    if key[:1].isalnum():
                        pattern = r"\b" + pattern
                    if key[-1:].isalnum():
                        pattern = pattern + r"\b"
                    self._keyword_patterns[key] = re.compile(pattern, re.IGNORECASE)
            self._category_weights[category] = weights

        # Trailing "<sep> <site name>" fragments, longest first so that
        # "google docs" is tried before "google".
        self._site_suffix_re = re.compile(
            r"\s*[-–—|]\s*(?:%s)\s*$"
            % "|".join(
                re.escape(name)
                for name in sorted(self.SITE_SUFFIXES, key=len, reverse=True)
            ),
            re.IGNORECASE,
        )

        # Pre‑compute embeddings for each label text using the shared embedder.
        # Only persistable labels are scored: a category the schema rejects is
        # worse than no category, and dropping it here lets similarity fall
        # through to the nearest label that can actually be stored.
        self._label_embeddings: Dict[str, List[float]] = {}
        for label, text in self.LABEL_TEXTS.items():
            if label not in self.PERSISTABLE_CATEGORIES:
                continue
            self._label_embeddings[label] = embedder.generate_embedding(text)

        # Supervised learning components
        self._supervised_model: Optional[LogisticRegression] = None
        self._label_encoder: Optional[LabelEncoder] = None
        self._model_version: str = "0.0.0"
        self._min_training_samples: int = 10
        self._retrain_threshold: int = 5
        self._model_lock = threading.Lock()
        self._new_labels_since_training: int = 0
        # How much more a typed correction counts than a backfilled label.
        self._USER_LABEL_WEIGHT: float = 5.0
        # Upper bound on already-trained labels carried into a retrain, newest
        # first. Generous enough to keep the whole history at present scale;
        # it exists to bound memory, not to forget.
        self._max_retained_training_labels: int = 50_000

    def record_user_correction(
        self,
        segment: ActivitySegmentRecord,
        correct_label: str,
        source: str = "user",
    ) -> str:
        """Store a label for a segment and return the label record ID.

        Does NOT trigger retraining; that is handled by the caller if desired.

        Args:
            segment: The activity segment being labelled.
            correct_label: The label to store.
            source: ``"user"`` for a correction someone typed, ``"backfill"``
                for one derived by a repair script. See
                :class:`ActivitySegmentLabelRecord`.
        """
        # Validate the label
        valid_labels = set(self.CATEGORY_KEYWORDS.keys()) | {"meetings", "other", "idle"}
        if correct_label not in valid_labels:
            raise ValueError(
                f"Invalid label '{correct_label}'. Must be one of: {sorted(valid_labels)}"
            )

        # Rebuild the embedding exactly as the classifier would at predict
        # time — same normalisation, same text — or the model trains on
        # vectors it will never be asked to score.
        text = self.build_text(segment)
        seg_emb = embedder.generate_embedding(text) if text else []

        # Store the correction in the database
        db = SessionLocal()
        try:
            label_record = ActivitySegmentLabelRecord(
                id=str(uuid.uuid4()),
                segment_id=segment.id,
                user_id=segment.user_id,
                device_id=segment.device_id,
                model_name=embedder.model_name,
                model_version=embedder.model_version,
                dimensions=embedder.dimensions,
                embedding=json.dumps(seg_emb) if seg_emb else None,
                correct_label=correct_label,
                source=source,
            )
            db.add(label_record)
            db.commit()
            db.refresh(label_record)
            return label_record.id
        finally:
            db.close()

    def store_user_correction(
        self,
        segment: ActivitySegmentRecord,
        correct_label: str,
    ) -> None:
        """Store a user-provided correction for supervised learning.

        Args:
            segment: The activity segment that was corrected
            correct_label: The correct label provided by the user
        """
        # Delegate to the new method but ignore the return value for backward compatibility.
        _ = self.record_user_correction(segment, correct_label)
        seg_emb = embedder.embed_segment(segment) or []

        # DEV-ONLY: Google Sheets synchronization (REMOVE AFTER DEVELOPMENT)
        if os.getenv("ENABLE_GSHEET_SYNC", "false").lower() == "true":
            try:
                import gspread
                from datetime import datetime
                # Uses cached credentials from one-time `gspread.oauth()` call
                gc = gspread.oauth()
                sh = gc.open_by_key("1G_oudT83kv-JSugqzbVE-nbLyjmQ0c7YY5EGpbLUaG8")
                worksheet = sh.worksheet("Labels")
                worksheet.append_row([
                    datetime.now().isoformat(),                    # timestamp
                    segment.id,                                    # segment_id
                    segment.user_id,                               # user_id
                    correct_label,                                 # label
                    json.dumps(seg_emb),                           # embedding (JSON string)
                    segment.device_id or "",                       # device_id
                    segment.app_name or "",                        # app_name
                    segment.title or "",                           # title
                    segment.detail or ""                           # detail
                ])
            except Exception as e:
                # Never let a sheet failure break the main correction flow
                print(f"[DEV] Google Sheet sync failed (non‑critical): {e}")

        # Increment counter and check if we should retrain (same logic as before)
        with self._model_lock:
            self._new_labels_since_training += 1
            if self._new_labels_since_training >= self._retrain_threshold:
                # Train in background to avoid blocking
                training_thread = threading.Thread(
                    target=self._train_supervised_model, daemon=False
                )
                training_thread.start()

    def train_from_labels(self) -> Dict[str, Any]:
        """Train the supervised model on every stored label, now.

        The automatic path only fires after five *new* corrections arrive
        through the feedback route, which a bulk backfill never trips: it
        writes label rows straight to the table. Without this entry point
        thousands of usable training rows would sit unread.

        Returns a summary of what was trained, or ``{"trained": False}`` with
        a reason. The model lives in this process's memory and is not
        persisted, so a restart reverts to rules and embeddings until
        something trains it again.
        """
        return self._train_supervised_model(force=True) or {"trained": False}

    def _train_supervised_model(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Train or retrain the supervised learning model using stored labels."""
        print("[TRAIN] Entering _train_supervised_model")
        # Avoid concurrent training
        with self._model_lock:
            # Check if we have enough new labels to justify retraining
            if not force and self._new_labels_since_training < self._retrain_threshold:
                print(f"[TRAIN] Not enough new labels: {self._new_labels_since_training} < {self._retrain_threshold}")
                return None

            # Get all labels from the database
            db = SessionLocal()
            try:
                label_records = (
                    db.query(ActivitySegmentLabelRecord)
                    .filter(ActivitySegmentLabelRecord.used_in_training == False)
                    .all()
                )

                # Also include previously used labels, so a retrain refines the
                # model instead of replacing it with whatever arrived since.
                # This cap was 50, which was ample when the table held 26 rows
                # and catastrophic once it held 4,197: every retrain would have
                # thrown away 99% of the training set and relearned the task
                # from the handful of newest corrections.
                used_labels = (
                    db.query(ActivitySegmentLabelRecord)
                    .filter(ActivitySegmentLabelRecord.used_in_training == True)
                    .order_by(ActivitySegmentLabelRecord.created_at.desc())
                    .limit(self._max_retained_training_labels)
                    .all()
                )

                all_label_records = label_records + used_labels
                print(
                    f"[TRAIN] Found {len(label_records)} unused labels and "
                    f"{len(used_labels)} used labels "
                    f"(cap {self._max_retained_training_labels})"
                )

                if len(all_label_records) < self._min_training_samples:
                    # Not enough data to train yet
                    print(f"[TRAIN] Not enough total labels: {len(all_label_records)} < {self._min_training_samples}")
                    return None

                # Prepare training data. A row whose embedding is missing or
                # the wrong width is dropped rather than appended: an empty
                # list among the vectors makes the feature matrix ragged, and
                # numpy builds an object array that fit() rejects with an
                # error naming neither the row nor the reason.
                embeddings: List[List[float]] = []
                labels: List[str] = []
                weights: List[float] = []
                skipped = 0

                for record in all_label_records:
                    try:
                        embedding = json.loads(record.embedding) if record.embedding else []
                    except (json.JSONDecodeError, TypeError):
                        skipped += 1
                        continue
                    if len(embedding) != embedder.dimensions:
                        skipped += 1
                        continue
                    embeddings.append(embedding)
                    labels.append(record.correct_label)
                    # A label someone typed is evidence of what they meant; a
                    # backfilled one is a rule's opinion, and there are two
                    # orders of magnitude more of them. Left unweighted, the
                    # corrections would be rounding error.
                    weights.append(
                        self._USER_LABEL_WEIGHT if record.source == "user" else 1.0
                    )

                print(f"[TRAIN] After processing, we have {len(embeddings)} embeddings ({skipped} skipped)")
                if len(embeddings) < self._min_training_samples:
                    print(f"[TRAIN] Not enough valid embeddings: {len(embeddings)} < {self._min_training_samples}")
                    return None

                # Encode labels
                if self._label_encoder is None:
                    self._label_encoder = LabelEncoder()
                y = self._label_encoder.fit_transform(labels)

                # Train logistic regression model
                X = np.array(embeddings)
                sample_weight = np.array(weights)
                print(f"[TRAIN] Training model with X.shape={X.shape}, y.shape={y.shape}")
                model = LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                    random_state=42,
                    # The label distribution is heavily skewed — thousands of
                    # 'learn' against tens of 'other' — and an unweighted fit
                    # buys its accuracy by never predicting the rare labels.
                    class_weight="balanced",
                )
                model.fit(X, y, sample_weight=sample_weight)

                holdout_accuracy = self._holdout_accuracy(X, y, sample_weight)

                # Update model and label encoder
                self._supervised_model = model
                self._model_version = f"{int(self._model_version.split('.')[0]) + 1}.0.0"

                # Mark labels as used in training
                for record in label_records:
                    record.used_in_training = True
                db.commit()

                # Reset counter only after successful training
                print(f"[TRAIN] Training complete. Resetting _new_labels_since_training from {self._new_labels_since_training} to 0")
                self._new_labels_since_training = 0

                return {
                    "trained": True,
                    "samples": len(embeddings),
                    "skipped": skipped,
                    "classes": list(self._label_encoder.classes_),
                    "model_version": self._model_version,
                    "holdout_accuracy": holdout_accuracy,
                }
            except Exception as e:
                # In case of error, log and continue
                # In a real application, you'd want to log this properly
                print(f"[TRAIN] Exception occurred: {e}")
                import traceback
                traceback.print_exc()
                return {"trained": False, "error": str(e)}
            finally:
                db.close()

    def _holdout_accuracy(
        self,
        X: "np.ndarray",
        y: "np.ndarray",
        sample_weight: "np.ndarray",
    ) -> Optional[float]:
        """Accuracy on a held-out split, or None if the data cannot support one.

        Reported so the caller has a number that is not the training score.
        It measures agreement with the stored labels, which for backfilled
        rows means agreement with the rule layer — not correctness.
        """
        try:
            from sklearn.model_selection import train_test_split

            _, counts = np.unique(y, return_counts=True)
            if len(counts) < 2 or counts.min() < 2 or len(y) < 20:
                return None
            X_train, X_test, y_train, y_test, w_train, _ = train_test_split(
                X, y, sample_weight, test_size=0.2, random_state=42, stratify=y
            )
            probe = LogisticRegression(
                max_iter=1000, solver="lbfgs", random_state=42, class_weight="balanced"
            )
            probe.fit(X_train, y_train, sample_weight=w_train)
            return float(probe.score(X_test, y_test))
        except Exception:
            return None

    # --------------------------------------------------------------------- #
    # Text normalisation
    # --------------------------------------------------------------------- #
    def clean_title(self, title: Optional[str]) -> str:
        """Strip browser and site boilerplate, returning just the page topic.

        ``"Point Estimation - MoM and MLE - YouTube - Comet"`` becomes
        ``"Point Estimation - MoM and MLE"``. Suffixes are peeled repeatedly
        because they nest: page title, then site, then browser.
        """
        if not title:
            return ""
        # Edge writes a zero-width space into "Microsoft​ Edge".
        text = title.replace("​", "").strip()
        previous: Optional[str] = None
        while previous != text and text:
            previous = text
            text = self._BROWSER_SUFFIX_RE.sub("", text).strip()
            text = self._site_suffix_re.sub("", text).strip()
            # A title that is *only* a site name ("Google Gemini - Comet")
            # names the tab, not the work done in it.
            if text.lower() in self.SITE_SUFFIXES:
                text = ""
        return text

    def is_chrome_title(self, title: Optional[str]) -> bool:
        """True when a title names application furniture rather than content.

        An empty result is deliberately *not* chrome: a title of "Google
        Gemini - Comet" cleans down to nothing, but the URL still says which
        site it was, and that is better information than "system".
        """
        cleaned = self.clean_title(title).strip().lower()
        return bool(cleaned) and cleaned in self.CHROME_TITLES

    @staticmethod
    def _parse_url(detail: Optional[str]) -> Tuple[Optional[str], str]:
        """Return ``(host, path)`` for an http(s) detail, else ``(None, "")``."""
        if not detail:
            return None, ""
        candidate = detail.strip()
        if not candidate.lower().startswith(("http://", "https://")):
            return None, ""
        try:
            parsed = urlparse(candidate)
        except ValueError:
            return None, ""
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return (host or None), parsed.path

    @staticmethod
    def _host_matches(host: str, pattern: str) -> bool:
        """Exact host match, or a dotted-suffix match on a subdomain."""
        return host == pattern or host.endswith("." + pattern)

    def _lookup_host(
        self,
        host: str,
        table: Iterable[Tuple[str, str]],
    ) -> Optional[str]:
        for pattern, category in table:
            if self._host_matches(host, pattern):
                return category
        return None

    def build_text(self, segment: ActivitySegmentRecord) -> str:
        """Build the text the embedding classifier sees for a segment.

        Boilerplate is removed and the URL is reduced to its host: a full
        Moodle URL is 90 characters of ``pluginfile.php/10528/mod_resource``
        that swamp the handful of words actually describing the activity.

        Training embeddings are built through this same method, so a stored
        correction and a live prediction describe the segment identically.
        """
        parts: List[str] = []

        title = self.clean_title(segment.title)
        if title:
            parts.append(title)

        host, _path = self._parse_url(segment.detail)
        if host:
            # A host the rules already recognise is left out: the rules have
            # extracted everything it has to say, and repeating it here only
            # pulls the vector toward the site and away from the topic. An
            # unknown host is kept — it may be the only clue there is.
            known = (
                self._lookup_host(host, self.DECISIVE_HOSTS)
                or self._lookup_host(host, self.FALLBACK_HOSTS)
                or self._LOCAL_HOST_RE.match(host)
            )
            if not known:
                parts.append(host)
        elif segment.detail and not segment.detail.lower().startswith(("http://", "https://")):
            # Non-URL details (file paths, IDE workspace names) are content.
            parts.append(segment.detail)

        # The application name is included only when nothing else survived, so
        # that the same browser name is not prepended to every browser segment.
        if not parts and segment.app_name:
            parts.append(segment.app_name)

        return " ".join(parts)

    # --------------------------------------------------------------------- #
    # Evidence-based rules
    # --------------------------------------------------------------------- #
    def _meeting_evidence(self, segment: ActivitySegmentRecord) -> Optional[float]:
        """Return a confidence if a conferencing tool was demonstrably open.

        Returns ``None`` otherwise — and ``None`` is the only other outcome,
        which is the point: "meetings" is now unreachable by resemblance.
        """
        app = (segment.app_name or "").strip().lower()
        if app in self.MEETING_APPS:
            return 0.95

        host, _path = self._parse_url(segment.detail)
        if host and any(self._host_matches(host, h) for h in self.MEETING_HOSTS):
            return 0.95

        title = self.clean_title(segment.title)
        if title and self._MEETING_TITLE_RE.match(title):
            return 0.8

        return None

    def categorize_by_host(
        self,
        segment: ActivitySegmentRecord,
    ) -> Tuple[Optional[str], Optional[str], float]:
        """Classify from the URL host.

        Returns ``(category, tier, confidence)`` where tier is ``"decisive"``
        (the host settles it) or ``"fallback"`` (the page title may overrule
        it), and ``(None, None, 0.0)`` when the host is unknown.
        """
        host, path = self._parse_url(segment.detail)
        if not host:
            return None, None, 0.0

        if self._LOCAL_HOST_RE.match(host):
            return "work", "decisive", 0.8

        category = self._lookup_host(host, self.DECISIVE_HOSTS)
        if category:
            return category, "decisive", 0.9

        # An unknown host serving LMS URLs is a university's own Moodle.
        if path and self._LMS_PATH_RE.search(path):
            return "learn", "decisive", 0.85

        category = self._lookup_host(host, self.FALLBACK_HOSTS)
        if category:
            return category, "fallback", 0.55

        return None, None, 0.0

    # --------------------------------------------------------------------- #
    # Rule‑based classification
    # --------------------------------------------------------------------- #
    def categorize_by_rules(
        self,
        title: Optional[str],
        detail: Optional[str],
        app_name: Optional[str],
    ) -> Tuple[Optional[str], float]:
        """Categorize an activity segment using rule‑based matching.

        Args:
            title: Window title or application title
            detail: Additional detail (URL, file path, etc.)
            app_name: Application name

        Returns:
            Tuple of (category, confidence) where confidence is 0‑1,
            or (None, 0.0) if no match found
        """
        # Combine all text sources for analysis
        text_parts: List[str] = []
        if title:
            text_parts.append(title.lower())
        if detail:
            text_parts.append(detail.lower())
        if app_name:
            text_parts.append(app_name.lower())

        combined_text = " ".join(text_parts)
        if not combined_text.strip():
            return None, 0.0

        # Score each category
        category_scores: Dict[str, float] = {}
        for category, weights in self._category_weights.items():
            score = 0.0
            matched_keywords = 0
            for keyword, weight in weights.items():
                if self._keyword_patterns[keyword].search(combined_text):
                    score += weight
                    matched_keywords += 1

            # Normalize by number of matched keywords to avoid bias toward
            # categories with more keywords
            if matched_keywords > 0:
                category_scores[category] = score / math.log(matched_keywords + 1)
            else:
                category_scores[category] = 0.0

        # Find the category with the highest score
        if not category_scores or max(category_scores.values()) == 0:
            return None, 0.0

        best_category = max(category_scores, key=category_scores.get)
        confidence = min(category_scores[best_category] / 10.0, 1.0)  # Cap at 1.0

        return best_category if confidence > 0.1 else None, confidence

    # --------------------------------------------------------------------- #
    # Embedding‑based classification
    # --------------------------------------------------------------------- #
    def score_labels(self, segment_embedding: List[float]) -> Dict[str, float]:
        """Return the raw cosine similarity to every eligible label text.

        Raw, not rescaled: ``(cosine + 1) / 2`` used to be reported as the
        confidence, which compressed everything into [0.5, 0.7] and made the
        acceptance threshold unreachable. Callers need the true values to see
        how weak these matches are — the median winner on browser segments
        scored 0.28.
        """
        if not segment_embedding:
            return {}

        seg_vec = np.array(segment_embedding).reshape(1, -1)
        similarities: Dict[str, float] = {}
        for category, label_emb in self._label_embeddings.items():
            if category in self.EMBEDDING_EXCLUDED_LABELS:
                continue
            label_vec = np.array(label_emb).reshape(1, -1)
            # Embeddings are L2-normed, so this is cosine similarity in [-1, 1].
            similarities[category] = float(cosine_similarity(seg_vec, label_vec)[0][0])
        return similarities

    def categorize_by_embedding(
        self,
        segment_embedding: List[float],
    ) -> Tuple[Optional[str], float]:
        """Categorize an activity segment using embedding similarity to label texts.

        Args:
            segment_embedding: The embedding vector for the segment

        Returns:
            Tuple of (category, confidence) where confidence is the raw cosine
            similarity clamped to [0, 1], or (None, 0.0) if no match found.
            The caller is responsible for deciding whether that similarity is
            good enough; see :meth:`_predict_uncapped`.
        """
        similarities = self.score_labels(segment_embedding)
        if not similarities:
            return None, 0.0

        best_category = max(similarities, key=similarities.get)
        return best_category, max(0.0, similarities[best_category])

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def predict(
        self,
        segment: ActivitySegmentRecord,
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Classify a segment, guaranteeing a storable category.

        Thin wrapper over :meth:`_predict_uncapped` that drops any label the
        schema would reject. The rule table, the zero-shot label texts and a
        retrained supervised model can each name categories the CHECK
        constraint does not list; persisting is a batch operation, so one such
        row used to discard every segment built in that window.
        """
        category, method, confidence = self._predict_uncapped(segment)
        if category is not None and category not in self.PERSISTABLE_CATEGORIES:
            aliased = self.CATEGORY_ALIASES.get(category)
            if aliased is not None:
                return aliased, method, confidence
            logger.warning(
                "Dropping unstorable category %r (method=%s) for segment app=%r; "
                "add it to ck_activity_segments_category to keep it.",
                category, method, segment.app_name,
            )
            return None, None, None
        return category, method, confidence

    def _predict_uncapped(
        self,
        segment: ActivitySegmentRecord,
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Return the best category, method, and confidence for a segment.

        Evidence is consulted before resemblance, because the embedding
        classifier cannot answer "I don't know" — it returns its nearest label
        whatever it is shown, so anything it can be spared it should be:

          1. Conferencing app or URL open → ``meetings``. The only route there.
          2. A known URL host → its category.
          3. A title that is only browser or OS furniture → ``system``.
          4. Keyword rules → if confident enough.
          5. Supervised model → if trained and confident enough.
          6. Embeddings → only on a strong, unambiguous match.
          7. A known-but-generic host, or a low-confidence rule hit.

        Args:
            segment: Activity segment to classify.

        Returns:
            Tuple of (category, category_method, confidence) where:
                - category is the predicted label or None
                - category_method is 'rule', 'supervised', 'embedding', or None
                - confidence is a float between 0‑1 or None
        """
        from app.core.config import settings

        threshold = settings.CATEGORIZATION_THRESHOLD

        # ---------- Step 1: conferencing evidence ----------
        meeting_conf = self._meeting_evidence(segment)
        if meeting_conf is not None:
            return "meetings", "rule", meeting_conf

        # ---------- Step 2: URL host ----------
        host_category, host_tier, host_conf = self.categorize_by_host(segment)
        if host_tier == "decisive":
            return host_category, "rule", host_conf

        # ---------- Step 3: browser / OS chrome ----------
        # Nothing describing the user's activity survived normalisation, so
        # there is no topic for the embedding classifier to match — and it
        # would match one regardless. Prefer what the host says the site is;
        # failing that, the browser's own UI is system activity.
        cleaned_title = self.clean_title(segment.title)
        is_chrome = self.is_chrome_title(segment.title)
        if is_chrome or not cleaned_title:
            if host_category is not None:
                return host_category, "rule", host_conf
            if is_chrome:
                return "system", "rule", 0.7
            if (segment.app_name or "").strip().lower() in self.BROWSER_APPS:
                return "system", "rule", 0.6

        # ---------- Step 4: rule‑based ----------
        rule_category, rule_conf = self.categorize_by_rules(
            segment.title, segment.detail, segment.app_name
        )
        if rule_category is not None and rule_conf >= threshold:
            return rule_category, "rule", rule_conf

        # The embedding is shared by steps 5 and 6; it was previously computed
        # twice per segment, which doubled the cost of every rebuild.
        text = self.build_text(segment)
        seg_emb = embedder.generate_embedding(text) if text else None

        # ---------- Step 5: supervised learning ----------
        with self._model_lock:
            if (
                self._supervised_model is not None
                and self._label_encoder is not None
                and seg_emb is not None
            ):
                try:
                    proba = self._supervised_model.predict_proba([seg_emb])[0]
                    max_confidence = float(max(proba))
                    predicted_class_idx = proba.argmax()

                    if max_confidence >= threshold:
                        predicted_label = self._label_encoder.classes_[predicted_class_idx]
                        return predicted_label, "supervised", max_confidence
                except Exception:
                    # If supervised prediction fails, fall back to embedding
                    pass

        # ---------- Step 6: embedding‑based ----------
        if seg_emb is not None:
            similarities = self._apply_youtube_heuristics(
                self.score_labels(seg_emb), segment, cleaned_title
            )
            ranked = sorted(similarities.items(), key=lambda kv: kv[1], reverse=True)
            if len(ranked) >= 2:
                (top_label, top_sim), (_, runner_up_sim) = ranked[0], ranked[1]
                margin = top_sim - runner_up_sim
                # Both bars matter. The similarity bar rejects segments no
                # label really describes; the margin bar rejects segments where
                # several labels describe them equally badly. Browser chrome
                # failed both, and was accepted anyway.
                if (
                    top_sim >= settings.EMBEDDING_MIN_SIMILARITY
                    and margin >= settings.EMBEDDING_MIN_MARGIN
                ):
                    return top_label, "embedding", min(max(top_sim, 0.0), 1.0)

        # ---------- Step 7: weaker signals, in order of trustworthiness ----------
        if host_category is not None:
            return host_category, "rule", host_conf

        if rule_category is not None:
            return rule_category, "rule", rule_conf

        # No confident classification found
        return None, None, None

    def _apply_youtube_heuristics(
        self,
        similarities: Dict[str, float],
        segment: ActivitySegmentRecord,
        cleaned_title: str,
    ) -> Dict[str, float]:
        """Nudge learn/entertainment for YouTube, which hosts both.

        Boosts are small on purpose: they are worth about half a typical
        margin between labels, enough to break a tie that the video's title
        genuinely settles, not enough to decide the outcome by themselves.
        """
        detail_lower = (segment.detail or "").lower()
        if "youtube.com" not in detail_lower and "youtu.be" not in detail_lower:
            return similarities

        adjusted = dict(similarities)
        title_lower = cleaned_title.lower()

        # A video is entertainment by default; the title can argue otherwise.
        if "entertainment" in adjusted:
            adjusted["entertainment"] += 0.05
        if "learn" in adjusted and self._YT_LEARN_KEYWORDS.search(title_lower):
            adjusted["learn"] += 0.05
        if "entertainment" in adjusted and self._YT_ENTERTAINMENT_KEYWORDS.search(title_lower):
            adjusted["entertainment"] += 0.05
        return adjusted


# Provide a module‑level singleton for convenience.
categorizer = Categorizer()