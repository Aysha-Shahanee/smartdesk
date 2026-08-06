"""Activity categorization service.

Implements rule-based, supervised learning, and embedding-based categorization
of activity segments into predefined categories: work, learn, communication,
entertainment, social_media, system, meetings, other.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

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
        self._category_weights: Dict[str, Dict[str, float]] = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            weights: Dict[str, float] = {}
            for keyword in keywords:
                # Longer phrases get higher weight
                weight = len(keyword.split()) * 0.5 + 1
                weights[keyword.lower()] = weight
            self._category_weights[category] = weights

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

    def record_user_correction(self, segment: ActivitySegmentRecord, correct_label: str) -> str:
        """Store a user-provided correction and return the label record ID.
        Does NOT trigger retraining; that is handled by the caller if desired.
        """
        # Validate the label
        valid_labels = set(self.CATEGORY_KEYWORDS.keys()) | {"meetings", "other", "idle"}
        if correct_label not in valid_labels:
            raise ValueError(
                f"Invalid label '{correct_label}'. Must be one of: {sorted(valid_labels)}"
            )

        # Get the embedding that was used for this segment's prediction
        seg_emb = embedder.embed_segment(segment)
        if seg_emb is None:
            # If we can't generate an embedding, we still store the correction
            # but without embedding (supervised learning won't be able to use it).
            seg_emb = []

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

    def _train_supervised_model(self) -> None:
        """Train or retrain the supervised learning model using stored labels."""
        print("[TRAIN] Entering _train_supervised_model")
        # Avoid concurrent training
        with self._model_lock:
            # Check if we have enough new labels to justify retraining
            if self._new_labels_since_training < self._retrain_threshold:
                print(f"[TRAIN] Not enough new labels: {self._new_labels_since_training} < {self._retrain_threshold}")
                return

            # Get all labels from the database
            db = SessionLocal()
            try:
                label_records = (
                    db.query(ActivitySegmentLabelRecord)
                    .filter(ActivitySegmentLabelRecord.used_in_training == False)
                    .all()
                )

                # Also include some previously used labels for stability
                used_labels = (
                    db.query(ActivitySegmentLabelRecord)
                    .filter(ActivitySegmentLabelRecord.used_in_training == True)
                    .order_by(ActivitySegmentLabelRecord.created_at.desc())
                    .limit(50)
                    .all()
                )

                all_label_records = label_records + used_labels
                print(f"[TRAIN] Found {len(label_records)} unused labels and {len(used_labels)} used labels (limited to 50)")

                if len(all_label_records) < self._min_training_samples:
                    # Not enough data to train yet
                    print(f"[TRAIN] Not enough total labels: {len(all_label_records)} < {self._min_training_samples}")
                    return

                # Prepare training data
                embeddings = []
                labels = []

                for record in all_label_records:
                    try:
                        embedding = json.loads(record.embedding) if record.embedding else []
                        embeddings.append(embedding)
                        labels.append(record.correct_label)
                    except (json.JSONDecodeError, TypeError):
                        # Skip invalid embeddings
                        continue

                print(f"[TRAIN] After processing, we have {len(embeddings)} embeddings")
                if len(embeddings) < self._min_training_samples:
                    print(f"[TRAIN] Not enough valid embeddings: {len(embeddings)} < {self._min_training_samples}")
                    return

                # Encode labels
                if self._label_encoder is None:
                    self._label_encoder = LabelEncoder()
                y = self._label_encoder.fit_transform(labels)

                # Train logistic regression model
                X = np.array(embeddings)
                print(f"[TRAIN] Training model with X.shape={X.shape}, y.shape={y.shape}")
                model = LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                    random_state=42,
                )
                model.fit(X, y)

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
            except Exception as e:
                # In case of error, log and continue
                # In a real application, you'd want to log this properly
                print(f"[TRAIN] Exception occurred: {e}")
                import traceback
                traceback.print_exc()
            finally:
                db.close()

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
            Tuple of (category, confidence) where confidence is 0‑1,
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

        # Apply YouTube heuristic boosts (if the detail contains a YouTube URL)
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
        """Classify a segment, guaranteeing a storable category.

        Thin wrapper over :meth:`_predict_uncapped` that drops any label the
        schema would reject. The rule table, the zero-shot label texts and a
        retrained supervised model can each name categories the CHECK
        constraint does not list; persisting is a batch operation, so one such
        row used to discard every segment built in that window.
        """
        category, method, confidence = self._predict_uncapped(segment)
        if category is not None and category not in self.PERSISTABLE_CATEGORIES:
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

        The method follows the flow described in the plan:
          1. Rule‑based classification → if confidence >= threshold, use it.
          2. Supervised learning classification → if model exists and confident, use it.
          3. Embedding‑based classification → if similarity >= threshold, use it.
          4. Fallback to rule‑based (or Return None if all fail).

        Args:
            segment: Activity segment to classify.

        Returns:
            Tuple of (category, category_method, confidence) where:
                - category is the predicted label or None
                - category_method is 'rule', 'supervised', 'embedding', or None
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

        # ---------- Step 2: supervised learning ----------
        # Check if we have a trained supervised model and enough confidence
        with self._model_lock:
            if self._supervised_model is not None and self._label_encoder is not None:
                try:
                    seg_emb = embedder.embed_segment(segment)
                    if seg_emb is not None:
                        # Get prediction probabilities from the supervised model
                        proba = self._supervised_model.predict_proba([seg_emb])[0]
                        max_confidence = max(proba)
                        predicted_class_idx = proba.argmax()

                        if max_confidence >= threshold:
                            predicted_label = self._label_encoder.classes_[predicted_class_idx]
                            return predicted_label, "supervised", max_confidence
                except Exception:
                    # If supervised prediction fails, fall back to embedding
                    pass

        # ---------- Step 3: embedding‑based ----------
        seg_emb = embedder.embed_segment(segment)
        if seg_emb is not None:
            emb_category, emb_conf = self.categorize_by_embedding(seg_emb)

            # Boost entertainment for YouTube URLs
            if segment.detail:
                detail_lower = segment.detail.lower()
                if "youtube.com" in detail_lower or "youtu.be" in detail_lower:
                    # Boost entertainment confidence
                    emb_vec = np.array(seg_emb).reshape(1, -1)
                    ent_vec = np.array(self._label_embeddings["entertainment"]).reshape(1, -1)
                    ent_sim = cosine_similarity(emb_vec, ent_vec)[0][0]
                    ent_conf = (ent_sim + 1) / 2
                    # Boost by 0.1, cap at 1.0
                    ent_conf_boosted = min(ent_conf + 0.1, 1.0)
                    if ent_conf_boosted > emb_conf:
                        emb_category = "entertainment"
                        emb_conf = ent_conf_boosted

            # YouTube title heuristics for learn vs entertainment
            if segment.detail:
                detail_lower = segment.detail.lower()
                if "youtube.com" in detail_lower or "youtu.be" in detail_lower:
                    title_lower = (segment.title or "").lower()
                    if self._YT_LEARN_KEYWORDS.search(title_lower):
                        # Boost learn similarity
                        if emb_category == "learn":
                            emb_conf = min(emb_conf + 0.1, 1.0)
                    if self._YT_ENTERTAINMENT_KEYWORDS.search(title_lower):
                        if emb_category == "entertainment":
                            emb_conf = min(emb_conf + 0.1, 1.0)

            if emb_category is not None and emb_conf >= threshold:
                return emb_category, "embedding", emb_conf

        # ---------- Step 4: fallback to rule‑based (low confidence) ----------
        # If we have a rule result (even if below threshold), we can still return it
        # with method='rule' as a last resort.
        if rule_category is not None:
            return rule_category, "rule", rule_conf

        # No confident classification found
        return None, None, None


# Provide a module‑level singleton for convenience.
categorizer = Categorizer()