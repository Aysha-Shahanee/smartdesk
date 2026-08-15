"""Rule registration.

Rules declare themselves with the :func:`rule` decorator and are indexed by
scope at import time. The index is what makes rule count nearly free: a live
tick iterates ``REGISTRY[Scope.LIVE]`` and never looks at the daily, weekly or
monthly families at all.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Callable

from app.services.recommendations.types import (
    Finding,
    FeatureContext,
    RuleSpec,
    Scope,
    Section,
    Severity,
)

logger = logging.getLogger("smartdesk.recommendations.registry")

REGISTRY: dict[Scope, list[RuleSpec]] = defaultdict(list)
BY_ID: dict[str, RuleSpec] = {}


def rule(
    *,
    id: str,
    version: int,
    scope: Scope,
    section: Section,
    severity: Severity,
    title: str,
    why: str,
    action: str,
    requires: set[str] | frozenset[str] = frozenset(),
    min_days: int = 0,
    cooldown: timedelta = timedelta(hours=6),
    min_n: int = 0,
    action_label: str | None = None,
) -> Callable:
    """Register a rule.

    ``title`` / ``why`` / ``action`` are ``str.format`` templates filled from
    the finding's ``facts``. Keeping the copy next to the predicate is
    deliberate: a rule and the sentence it produces change together, and a
    template that references a fact the predicate stopped emitting fails loudly
    in that rule's own test rather than silently rendering ``{run_min}``.
    """

    def decorate(fn: Callable[[FeatureContext], Finding | None]) -> Callable:
        if id in BY_ID:
            raise ValueError(f"duplicate rule id {id!r}")
        spec = RuleSpec(
            id=id,
            version=version,
            scope=scope,
            section=section,
            severity=severity,
            title=title,
            why=why,
            action=action,
            fn=fn,
            requires=frozenset(requires),
            min_days=min_days,
            cooldown=cooldown,
            min_n=min_n,
            action_label=action_label,
        )
        REGISTRY[scope].append(spec)
        BY_ID[id] = spec
        return fn

    return decorate


def load_all_rules() -> int:
    """Import every rule module so the decorators run. Returns the rule count.

    Called once at engine construction. Import order does not matter — rules
    never reference each other, only features.
    """
    from app.services.recommendations.rules import (  # noqa: F401
        daily,
        hygiene,
        live,
        monthly,
        planning,
        weekly,
    )

    total = sum(len(v) for v in REGISTRY.values())
    logger.info(
        "Loaded %d rules (%s)",
        total,
        ", ".join(f"{s.value}={len(REGISTRY[s])}" for s in Scope if REGISTRY[s]),
    )
    return total
