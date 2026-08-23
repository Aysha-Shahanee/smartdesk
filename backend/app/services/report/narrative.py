"""Report prose, assembled from templates.

Deterministic by construction: the only inputs are the fact base and the day's
date, so the same period always renders identically. Variant selection uses a
hash of the period rather than a random choice for exactly that reason —
consecutive days do not repeat a phrasing, but regenerating an old report does
not produce new words.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.recommendations.narrative import fmt_minutes, fmt_pct
from app.services.report.facts import Metric, ReportFacts


@dataclass
class Section:
    """One rendered part of a report."""

    key: str
    heading: str
    body: list[str]
    #: Findings rendered as cards by the UI rather than as prose.
    items: list[dict] | None = None


def _pick(options: list[str], seed: str) -> str:
    """Stable choice among equivalent phrasings.

    Hash rather than random: a report regenerated next month must read the
    same as it did the day it was written, or the golden-file test is
    meaningless and so is any claim of reproducibility.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def _format_metric(metric: Metric) -> str:
    if metric.unit == "min":
        return fmt_minutes(metric.value)
    if metric.unit == "share":
        return fmt_pct(metric.value)
    if metric.unit == "score":
        return f"{metric.value:.2f}"
    return f"{metric.value:.0f}"


def _comparison_clause(metric: Metric) -> str:
    """"...against a usual X" — omitted entirely when there is no baseline.

    A missing baseline means fewer than eight samples backed it, and inventing
    a comparison there would be the exact failure the engine is built to avoid.
    """
    if metric.baseline is None or metric.delta is None:
        return ""
    if metric.unit == "min" and abs(metric.delta) < 5:
        return ", about typical for you"
    if metric.unit == "share" and abs(metric.delta) < 0.03:
        return ", about typical for you"
    if metric.unit == "score" and abs(metric.delta) < 0.05:
        return ", about typical for you"

    baseline_text = _format_metric(
        Metric(metric.key, metric.label, metric.baseline, metric.unit)
    )
    direction = "above" if metric.delta > 0 else "below"
    return f", {direction} your usual {baseline_text}"


def build_sections(facts: ReportFacts) -> list[Section]:
    """The eight sections, in reading order. Empty ones are dropped."""
    seed = f"{facts.scope}:{facts.period_start}"
    sections: list[Section] = []

    if not facts.has_activity:
        return [Section(
            key="empty",
            heading="No activity recorded",
            body=[
                f"Nothing was tracked for {facts.period_label}. If the machine "
                f"was in use, the collector was not running."
            ],
        )]

    # 1 — Headline.
    sections.append(Section(
        key="headline", heading="In short", body=_headline(facts, seed)
    ))

    # 2 — Where the time went.
    if facts.categories:
        top = facts.categories[0]
        lines = [
            f"{top.name.capitalize()} took the largest share at "
            f"{fmt_minutes(top.minutes)} ({fmt_pct(top.share)} of tracked "
            f"active time)."
        ]
        if len(facts.categories) > 1:
            rest = ", ".join(
                f"{c.name} {fmt_pct(c.share)}" for c in facts.categories[1:4]
            )
            lines.append(f"Behind it: {rest}.")
        sections.append(Section(
            key="where", heading="Where the time went", body=lines
        ))

    # 3 — Focus profile.
    focus_lines = _focus_profile(facts)
    if focus_lines:
        sections.append(Section(
            key="focus", heading="Focus profile", body=focus_lines
        ))

    # 4 / 5 / 6 — the rule engine's own findings, split by what they are for.
    behaviour = facts.findings.get("behaviour", [])
    wins = [f for f in behaviour if f["severity"] == "low"]
    watch = [f for f in behaviour if f["severity"] != "low"]
    immediate = facts.findings.get("immediate", [])

    if watch or immediate:
        sections.append(Section(
            key="broke",
            heading="What got in the way",
            body=[],
            items=(watch + immediate)[:5],
        ))
    if wins:
        sections.append(Section(
            key="wins", heading="What went well", body=[], items=wins[:4]
        ))

    insights = facts.findings.get("insight", [])
    if insights:
        sections.append(Section(
            key="watch", heading="Also worth knowing", body=[], items=insights[:4]
        ))

    # A report says what happened. It used to end with two more sections:
    #
    #   7 "For next time"    — the `planning` findings, which the Recommendations
    #                          tab already surfaces, live and with their own
    #                          feedback controls. Printing them here duplicated
    #                          that surface and turned a record into advice.
    #   8 "How solid this is" — history depth and hygiene caveats. Data-quality
    #                          problems now have somewhere better to be: calendar
    #                          health sits in Settings, and the hygiene rules
    #                          still fire on the Recommendations tab.
    #
    # Both are dropped here rather than hidden in the UI, so the markdown and
    # PDF exports say exactly what the screen says.
    return sections


def _headline(facts: ReportFacts, seed: str) -> list[str]:
    active = facts.metric("active")
    deep = facts.metric("deep")
    lines: list[str] = []

    if active:
        # Variants are phrased so the period label always sits where a proper
        # noun belongs. An earlier set lowercased it mid-sentence, which turned
        # "Friday, 14 August 2026" into "friday, 14 august 2026".
        opener = _pick(
            [
                f"{facts.period_label} recorded {_format_metric(active)} of "
                f"tracked activity{_comparison_clause(active)}.",
                f"{facts.period_label}: {_format_metric(active)} of tracked "
                f"activity{_comparison_clause(active)}.",
                f"You were active for {_format_metric(active)} across "
                f"{facts.period_label}{_comparison_clause(active)}.",
            ],
            seed,
        )
        lines.append(opener)

    if deep and deep.value > 0:
        lines.append(
            f"Of that, {_format_metric(deep)} was uninterrupted, high-focus "
            f"work{_comparison_clause(deep)}."
        )
    elif deep:
        lines.append(
            "No stretch ran long enough at high enough focus to count as deep "
            "work — every block was under 25 minutes or below your own focus "
            "threshold."
        )

    # The single strongest finding, promoted into the opening paragraph.
    ranked = [f for group in facts.findings.values() for f in group]
    if ranked:
        best = max(ranked, key=lambda f: f["score"])
        noun = {"daily": "day", "weekly": "week", "monthly": "month"}[facts.scope]
        lines.append(f"The {noun}'s clearest signal: {best['title'].lower()}.")
    return lines


def _focus_profile(facts: ReportFacts) -> list[str]:
    lines: list[str] = []
    focus = facts.metric("focus")
    if focus and focus.value > 0:
        lines.append(
            f"Average focus scored {_format_metric(focus)}"
            f"{_comparison_clause(focus)}."
        )
    if len(facts.hours) >= 2:
        best, worst = facts.hours[0], facts.hours[1]
        lines.append(
            f"The {best.hour:02d}:00 hour was the strongest at "
            f"{best.focus:.2f}; {worst.hour:02d}:00 was the weakest at "
            f"{worst.focus:.2f}."
        )
    if facts.days:
        best_day = max(facts.days, key=lambda d: d.deep_min)
        if best_day.deep_min > 0:
            lines.append(
                f"{best_day.weekday} {best_day.date} carried the most deep "
                f"work at {fmt_minutes(best_day.deep_min)}."
            )
    fragmentation = facts.metric("fragmentation")
    if fragmentation and fragmentation.value > 0:
        lines.append(
            f"Activity arrived in {fragmentation.value:.0f} separate pieces "
            f"per active hour{_comparison_clause(fragmentation)}."
        )
    return lines


# _quality() lived here and rendered the "How solid this is" section. Removed
# with the section itself. ReportFacts.data_notes is still populated by
# _load_findings — it is the hygiene caveat list, and leaving it on the facts
# object keeps it available to anything that wants to reinstate a caveats
# surface without re-deriving it.


def render_markdown(facts: ReportFacts, sections: list[Section]) -> str:
    """The canonical export form. Every other format derives from these facts."""
    out: list[str] = [
        f"# SmartDesk {facts.scope} report",
        "",
        f"**{facts.period_label}**  ",
        f"Generated {facts.generated_at[:19].replace('T', ' ')}",
        "",
    ]

    if facts.metrics:
        # The "Your usual" column is dropped entirely when nothing fills it —
        # the monthly scope carries no comparisons, and a column of em-dashes
        # implies a missing value rather than one that was never defined.
        any_baseline = any(m.baseline is not None for m in facts.metrics)
        if any_baseline:
            out.append("| Metric | Value | Your usual |")
            out.append("| --- | ---: | ---: |")
        else:
            out.append("| Metric | Value |")
            out.append("| --- | ---: |")
        for metric in facts.metrics:
            row = f"| {metric.label} | {_format_metric(metric)} |"
            if any_baseline:
                usual = (
                    _format_metric(
                        Metric(metric.key, metric.label, metric.baseline, metric.unit)
                    )
                    if metric.baseline is not None else "—"
                )
                row += f" {usual} |"
            out.append(row)
        out.append("")

    for section in sections:
        out.append(f"## {section.heading}")
        out.append("")
        for line in section.body:
            out.append(line)
            out.append("")
        for item in section.items or []:
            out.append(f"**{item['title']}**  ")
            out.append(f"{item['why']}  ")
            out.append(f"*{item['action']}*  ")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def _escape(value: str) -> str:
    """Minimal HTML escaping. Report text is app-generated, but activity titles
    inside a finding are not — a window title containing "<script>" is entirely
    possible and must not reach the printer as markup."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_html(facts: ReportFacts, sections: list[Section]) -> str:
    """A self-contained page for printing.

    Styled for paper rather than for the app: a light ground regardless of the
    viewer's theme, because this exists to become a PDF and a dark PDF is a
    waste of toner and unreadable when printed.
    """
    # Same rule as the markdown table: no "Your usual" column at all when no
    # metric in this scope has a baseline, rather than a column of em-dashes.
    any_baseline = any(m.baseline is not None for m in facts.metrics)
    usual_header = '<th class="n">Your usual</th>' if any_baseline else ""

    rows = []
    for metric in facts.metrics:
        cells = (
            f"<tr><td>{_escape(metric.label)}</td>"
            f"<td class='n'>{_escape(_format_metric(metric))}</td>"
        )
        if any_baseline:
            usual = (
                _format_metric(
                    Metric(metric.key, metric.label, metric.baseline, metric.unit)
                )
                if metric.baseline is not None else "&mdash;"
            )
            cells += f"<td class='n muted'>{usual}</td>"
        rows.append(cells + "</tr>")

    body = []
    for section in sections:
        body.append(f"<h2>{_escape(section.heading)}</h2>")
        for line in section.body:
            body.append(f"<p>{_escape(line)}</p>")
        for item in section.items or []:
            body.append(
                "<div class='finding'>"
                f"<strong>{_escape(item['title'])}</strong>"
                f"<p>{_escape(item['why'])}</p>"
                f"<p class='action'>{_escape(item['action'])}</p>"
                "</div>"
            )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>SmartDesk {_escape(facts.scope)} report</title>
<style>
  @page {{ margin: 18mm; }}
  body {{ font-family: Georgia, "Times New Roman", serif; color: #14181f;
         background: #fff; line-height: 1.6; font-size: 11pt; margin: 0; }}
  header {{ border-bottom: 1px solid #c4cbd5; padding-bottom: 12px;
            margin-bottom: 20px; }}
  h1 {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; font-size: 20pt;
        margin: 0 0 6px; letter-spacing: -0.02em; }}
  .meta {{ font-family: Consolas, monospace; font-size: 8.5pt; color: #59616e;
           letter-spacing: 0.04em; text-transform: uppercase; }}
  h2 {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; font-size: 12pt;
        margin: 22px 0 8px; page-break-after: avoid; }}
  p {{ margin: 0 0 9px; max-width: 34em; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 8px;
           font-family: Consolas, monospace; font-size: 9.5pt; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #dfe3ea; }}
  th {{ font-size: 8pt; text-transform: uppercase; letter-spacing: 0.08em;
        color: #858d9a; }}
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.muted {{ color: #858d9a; }}
  .finding {{ border-left: 2px solid #b5701a; padding-left: 14px;
              margin: 0 0 14px; page-break-inside: avoid; }}
  .finding strong {{ display: block; margin-bottom: 4px; }}
  .action {{ font-style: italic; color: #3c4552; }}
</style></head>
<body>
<header>
  <h1>SmartDesk {_escape(facts.scope)} report</h1>
  <div class="meta">{_escape(facts.period_label)} &middot; generated
    {_escape(facts.generated_at[:19].replace("T", " "))} &middot;
    {facts.days_of_history} days of history</div>
</header>
<table><thead><tr><th>Metric</th><th class="n">Value</th>
{usual_header}</tr></thead><tbody>{"".join(rows)}</tbody></table>
{"".join(body)}
</body></html>
"""
