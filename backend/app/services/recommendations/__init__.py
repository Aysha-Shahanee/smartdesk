"""SmartDesk recommendation engine.

Local, rule-based, and personalised by statistics computed from the user's own
recorded history. No language model is involved anywhere: findings are computed
in Python and rendered through deterministic templates, so no number on screen
can be one the data does not support.
"""

from app.services.recommendations.engine import RecommendationEngine, engine

__all__ = ["RecommendationEngine", "engine"]
