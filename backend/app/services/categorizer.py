"""Activity categorization service.

Implements rule-based and embedding-based categorization of activity segments
into predefined categories: work, learn, communication, entertainment,
social_media, system, meetings, other.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.models.db import ActivitySegmentRecord
from app.services.embedder import embedder


class Categorizer:
    """Service for categorizing activity segments."""

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
            "ait",
            "azure",
            "gcp",
            "linux",
            "windows",
            "terminal",
            "console",
            "command",
            "admin",
            "readme",
            "ppt",
            "pptx",
            "pdf",
            "slide",
            "slideshow",
        ],
        "learn": [
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

    # YouTube‑specific heuristic boosts (applied after similarity scoring)
    _YT_LEARN_KEYWORDS = re.compile(
        r"\b(lecture|tutorial|course|lesson|education|training|how\s+to|explained|review|talk|conference|webinar)\b",
        re.I,
    )
    _YT_ENTERTAINMENT_KEYWORDS = re.compile(
        r"\b(music|song|gaming|live\s+stream|stream|lets\s+play|playthrough|review|unboxing|haul|vlog|comedy|funny|challenge|prank)\b",
        re.I,
    )

    def __init__(self) -> None:
        """Initialize the categorizer."""
        # Pre‑compute keyword weights for rule‑based classification
        self._category_weights: Dict[str, Dict[str, float]] = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            weights: Dict[str, float] = {}
            for keyword in keywords:
                # Longer phrases get higher weight
                weight = len(keyword.split()) * 0.5 + 1
                weights[keyword.lower()] = weight
            self._category_weights[category] = weights

        # Pre‑compute embeddings for each label text using the shared embedder
        self._label_embeddings: Dict[str, List[float]] = {}
        for label, text in self.LABEL_TEXTS.items():
            self._label_embeddings[label] = embedder.generate_embedding(text)

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
            Tuple of (category, confidence_score) where confidence is 0‑1,
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
                if keyword in combined_text:
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
    def categorize_by_embedding(
        self,
        segment_embedding: List[float],
    ) -> Tuple[Optional[str], float]:
        """Categorize an activity segment using embedding similarity to label texts.

        Args:
            segment_embedding: The embedding vector for the segment

        Returns:
            Tuple of (category, confidence_score) where confidence is 0‑1,
            or (None, 0.0) if no match found
        """
        if not segment_embedding:
            return None, 0.0

        # Compute cosine similarity with each label embedding
        similarities: Dict[str, float] = {}
        seg_vec = np.array(segment_embedding).reshape(1, -1)

        for category, label_emb in self._label_embeddings.items():
            label_vec = np.array(label_emb).reshape(1, -1)
            # cosine_similarity returns value in [-1, 1]; our embeddings are L2‑normed,
            # so the result is already in that range.
            sim = cosine_similarity(seg_vec, label_vec)[0][0]
            # Map from [-1, 1] to [0, 1] for confidence
            confidence = (sim + 1) / 2
            similarities[category] = confidence

        if not similarities:
            return None, 0.0

        # Pick the category with the highest raw similarity
        best_category = max(similarities, key=similarities.get)
        confidence = similarities[best_category]

        # Apply YouTube heuristic boosts if the detail contains a YouTube URL
        # Note: this method doesn't have access to the original segment fields,
        # so the boost will be applied later in the public `predict` method.
        return best_category, confidence

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def predict(
        self,
        segment: ActivitySegmentRecord,
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """Return the best category, method, and confidence for a segment.

        The method follows the flow described in the plan:
          1. Rule‑based classification → if confidence >= threshold, use it.
          2. Embedding‑based classification → if similarity >= threshold, use it.
          3. Fallback to rule‑based (or return None if both fail).

        Args:
            segment: Activity segment to classify.

        Returns:
            Tuple of (category, category_method, confidence) where:
                - category is the predicted label or None
                - category_method is 'rule', 'embedding', or None
                - confidence is a float between 0‑1 or None
        """
        # ---------- Step 1: rule‑based ----------
        rule_category, rule_conf = self.categorize_by_rules(
            segment.title, segment.detail, segment.app_name
        )
        from app.core.config import settings

        threshold = settings.CATEGORIZATION_THRESHOLD

        if rule_category is not None and rule_conf >= threshold:
            return rule_category, "rule", rule_conf

        # ---------- Step 2: embedding‑based ----------
        seg_emb = embedder.embed_segment(segment)
        if seg_emb is not None:
            emb_category, emb_conf = self.categorize_by_embedding(seg_emb)

            # Apply YouTube heuristic boosts if relevant
            if segment.detail:
                detail_lower = segment.detail.lower()
                if "youtube.com" in detail_lower or "youtu.be" in detail_lower:
                    title_lower = (segment.title or "").lower()
                    if self._YT_LEARN_KEYWORDS.search(title_lower):
                        # Boost learn similarity
                        if emb_category == "learn":
                            emb_conf = min(emb_conf + 0.1, 1.0)
                        # Also reduce confidence for competing categories slightly
                    if self._YT_ENTERTAINMENT_KEYWORDS.search(title_lower):
                        if emb_category == "entertainment":
                            emb_conf = min(emb_conf + 0.1, 1.0)

            if emb_category is not None and emb_conf >= threshold:
                return emb_category, "embedding", emb_conf

        # ---------- Step 3: fallback to rule‑based (low confidence) ----------
        # If we have a rule result (even if below threshold), we can still return it
        # with method='rule' as a last resort.
        if rule_category is not None:
            return rule_category, "rule", rule_conf

        # No confident classification found
        return None, None, None


# Provide a module‑level singleton for convenience.
categorizer = Categorizer()