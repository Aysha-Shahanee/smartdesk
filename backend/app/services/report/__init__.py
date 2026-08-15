"""Report generation.

Facts are computed, words are assembled. The renderer is a pure function of the
fact base, so a report regenerated months later is byte-identical to the one
first produced — a property worth having and one an LLM layer would have cost.
"""

from app.services.report.facts import ReportFacts, build_report_facts
from app.services.report.narrative import (
    build_sections,
    render_html,
    render_markdown,
)

__all__ = [
    "ReportFacts",
    "build_report_facts",
    "build_sections",
    "render_html",
    "render_markdown",
]
