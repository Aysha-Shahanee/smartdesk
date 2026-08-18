import { useEffect, useState } from 'react';
import {
  getRuleHealth,
  setRuleMuted,
  type RuleHealth,
  type RuleHealthReport,
} from '../services/api';

/**
 * Catalogue review: how each rule has actually performed.
 *
 * Seventy-four rules compete for one panel, and until this view existed a rule
 * dismissed on sight for three months looked exactly like one the user acts on
 * every time. The clinical-alert-fatigue literature is clear that a global
 * override rate says nothing — appropriateness varies enormously by alert type
 * — so the only useful cut is per rule.
 *
 * The verdict column is deliberately not a fixed bar. Each rule is measured
 * against this user's own acceptance rate, and only flagged when its whole
 * confidence interval sits below it, so a rule with three dismissals reads as
 * unproven rather than condemned.
 */

const VERDICT_LABEL: Record<RuleHealth['verdict'], string> = {
  below: 'Below your average',
  typical: 'No difference',
  unproven: 'Too few to judge',
  above: 'Above your average',
  silent: 'Never fired',
};

const VERDICT_COLOR: Record<RuleHealth['verdict'], string> = {
  below: 'var(--color-danger)',
  typical: 'var(--color-text-secondary)',
  unproven: 'var(--color-text-secondary)',
  above: 'var(--color-success)',
  silent: 'var(--color-text-secondary)',
};

const pct = (value: number | null): string =>
  value === null ? '—' : `${Math.round(value * 100)}%`;

const duration = (seconds: number | null): string => {
  if (seconds === null) return '—';
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
};

const RuleHealthPanel: React.FC = () => {
  const [report, setReport] = useState<RuleHealthReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [showSilent, setShowSilent] = useState(false);
  // Rules whose mute request is in flight, so the button cannot be
  // double-pressed while the round trip completes.
  const [pending, setPending] = useState<Record<string, boolean>>({});

  /** Toggle a rule, updating the row in place rather than refetching. */
  const toggleMute = async (rule: RuleHealth) => {
    const next = !rule.muted;
    setPending(p => ({ ...p, [rule.rule_id]: true }));
    try {
      await setRuleMuted(rule.rule_id, next);
      setReport(current =>
        current === null
          ? current
          : {
              ...current,
              muted_count: current.muted_count + (next ? 1 : -1),
              rules: current.rules.map(r =>
                r.rule_id === rule.rule_id ? { ...r, muted: next } : r,
              ),
            },
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not update the rule.');
    } finally {
      setPending(p => ({ ...p, [rule.rule_id]: false }));
    }
  };

  useEffect(() => {
    if (!open || report || loading) return;
    setLoading(true);
    getRuleHealth()
      .then(r => { setReport(r); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Could not reach the backend.');
        setLoading(false);
      });
  }, [open, report, loading]);

  const rules = (report?.rules ?? []).filter(
    r => showSilent || r.verdict !== 'silent',
  );
  const silentCount = (report?.rules ?? []).filter(r => r.verdict === 'silent').length;

  return (
    <section className="sd-card rule-health">
      <button
        className="rule-health-toggle"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span className="card-icon">🩺</span> Rule health
        <span className="rule-health-hint">
          {open ? 'hide' : 'how each rule has actually performed'}
        </span>
      </button>

      {open && (
        <div className="rule-health-body">
          {loading && <p className="dash-empty">Reading the feedback…</p>}
          {error && <p className="dash-empty">{error}</p>}

          {report && !loading && (
            <>
              <p className="rule-health-summary">
                {report.overall_judged === 0 ? (
                  <>
                    No cards have been judged yet, so no rule can be compared
                    against anything. Applying or dismissing cards is what
                    fills this in.
                  </>
                ) : (
                  <>
                    Across every rule you have applied{' '}
                    <strong>{pct(report.overall_acceptance)}</strong> of the{' '}
                    {report.overall_judged} cards you ruled on, out of{' '}
                    {report.overall_fired} shown. Each rule below is measured
                    against that figure, not against a fixed bar.
                  </>
                )}
              </p>

              <div className="rule-health-scroll">
                <table className="rule-health-table">
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Verdict</th>
                      <th className="num">Shown</th>
                      <th className="num">Applied</th>
                      <th className="num">Dismissed</th>
                      <th className="num">Acceptance</th>
                      <th className="num">PPV</th>
                      <th className="num">To dismiss</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map(rule => (
                      <tr
                        key={rule.rule_id}
                        className={rule.muted ? 'rule-health-muted' : undefined}
                      >
                        <td>
                          <span className="rule-health-id">{rule.rule_id}</span>
                          {rule.scope && (
                            <span className="rule-health-scope">{rule.scope}</span>
                          )}
                          {!rule.known && (
                            <span className="rule-health-scope">retired</span>
                          )}
                          {rule.muted && (
                            <span className="rule-health-scope">muted</span>
                          )}
                        </td>
                        <td>
                          <span style={{ color: VERDICT_COLOR[rule.verdict] }}>
                            {VERDICT_LABEL[rule.verdict]}
                          </span>
                        </td>
                        <td className="num">{rule.fired || '—'}</td>
                        <td className="num">{rule.applied || '—'}</td>
                        <td className="num">{rule.dismissed || '—'}</td>
                        <td className="num">
                          {pct(rule.acceptance)}
                          {rule.acceptance_low !== null && (
                            <span className="rule-health-ci">
                              {' '}({pct(rule.acceptance_low)}–{pct(rule.acceptance_high)})
                            </span>
                          )}
                        </td>
                        <td className="num">{pct(rule.ppv)}</td>
                        <td className="num">
                          {duration(rule.median_seconds_to_dismiss)}
                        </td>
                        <td>
                          <button
                            className="rule-health-mute"
                            disabled={pending[rule.rule_id] || !rule.known}
                            onClick={() => toggleMute(rule)}
                            title={
                              rule.muted
                                ? 'Start showing this rule again'
                                : 'Stop showing cards from this rule'
                            }
                          >
                            {rule.muted ? 'Unmute' : 'Mute'}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {rules.length === 0 && (
                      <tr>
                        <td colSpan={9} className="dash-empty">
                          No rule has fired yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {silentCount > 0 && (
                <button
                  className="rule-health-more"
                  onClick={() => setShowSilent(s => !s)}
                >
                  {showSilent ? 'Hide' : 'Show'} {silentCount} rule
                  {silentCount === 1 ? '' : 's'} that never fired
                </button>
              )}

              {report.muted_count > 0 && (
                <p className="rule-health-summary">
                  {report.muted_count} rule{report.muted_count === 1 ? ' is' : 's are'}{' '}
                  muted and will not produce cards. Their history is kept.
                </p>
              )}

              <p className="rule-health-footnote">
                Acceptance is applied ÷ judged, with a 95% interval — a rule is
                only marked below your average when the whole interval sits
                under it. PPV is applied ÷ shown, the share of everything this
                rule put in front of you that you acted on. Muting takes
                effect the next time cards are generated; nothing already
                recorded is removed.
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
};

export default RuleHealthPanel;
