import { useEffect, useState } from 'react';
import {
  getEvaluation,
  getRecommendationPreferences,
  getSimulation,
  setBaselineEpoch,
  setSensitivity,
  type EvaluationReport,
  type RecommendationPreferences,
  type SimulationReport,
} from '../services/api';

/**
 * The controls that let you correct the engine, and the evidence that it works.
 *
 * Explainability research draws a line between an explanation you can read and
 * one you can act on — Tintarev & Masthoff (2012) call the second scrutability,
 * and tie it to whether a user ends up trusting the system. Every card already
 * names the rule behind it and shows the evidence; these are the levers that
 * make that information worth having.
 *
 * The evaluation half is the other direction: not what you can tell the engine,
 * but what the engine can honestly tell you about itself. It reports the
 * ordering against ablations of itself, including a shuffle, because a
 * precision figure with nothing to compare against says almost nothing.
 */

const pct = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;

const STRATEGY_LABEL: Record<string, string> = {
  engine: 'Engine (live)',
  rules_only: 'Rules only, no ranker',
  frequent: 'Most-accepted rule',
  severity: 'Severity only',
  random: 'Random order',
};

const SENSITIVITY_LABEL = (value: number): string => {
  if (value < 0.8) return 'Speaks up sooner';
  if (value > 1.2) return 'Only unusual days';
  return 'Default';
};

const EngineControlsPanel: React.FC = () => {
  const [prefs, setPrefs] = useState<RecommendationPreferences | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationReport | null>(null);
  const [simulation, setSimulation] = useState<SimulationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [epochDraft, setEpochDraft] = useState('');

  useEffect(() => {
    if (!open || prefs) return;
    Promise.all([
      getRecommendationPreferences(),
      getEvaluation(),
      getSimulation(),
    ])
      .then(([p, e, s]) => {
        setPrefs(p);
        setEvaluation(e);
        setSimulation(s);
        setEpochDraft(p.baseline_epoch ?? '');
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : 'Could not reach the backend.'),
      );
  }, [open, prefs]);

  const applySensitivity = async (value: number) => {
    setSaving(true);
    try {
      const result = await setSensitivity(value);
      setPrefs(p => (p ? { ...p, sensitivity: result.sensitivity } : p));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const applyEpoch = async (date: string | null) => {
    setSaving(true);
    try {
      const result = await setBaselineEpoch(date);
      setPrefs(p => (p ? { ...p, baseline_epoch: result.baseline_epoch } : p));
      setEpochDraft(result.baseline_epoch ?? '');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="sd-card rule-health">
      <button
        className="rule-health-toggle"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span className="card-icon">🎚️</span> Engine controls
        <span className="rule-health-hint">
          {open ? 'hide' : 'tune it, and see how well it is doing'}
        </span>
      </button>

      {!open ? null : error ? (
        <p className="dash-empty">{error}</p>
      ) : !prefs ? (
        <p className="dash-empty">Loading…</p>
      ) : (
        <div className="rule-health-body">
          {/* ---- Sensitivity ---- */}
          <div className="engine-control">
            <h4>How much is worth mentioning</h4>
            <p className="rule-health-summary">
              A day has to sit this far from your usual before a comparative
              rule says anything. Lower speaks up sooner; higher waits for
              something more unusual.
            </p>
            <div className="engine-slider-row">
              <input
                type="range"
                min={0.5}
                max={2}
                step={0.05}
                value={prefs.sensitivity}
                disabled={saving}
                onChange={e => applySensitivity(Number(e.target.value))}
              />
              <span className="engine-slider-value">
                {prefs.sensitivity.toFixed(2)}×{' '}
                <em>{SENSITIVITY_LABEL(prefs.sensitivity)}</em>
              </span>
            </div>
          </div>

          {/* ---- Baseline epoch ---- */}
          <div className="engine-control">
            <h4>Start comparing from</h4>
            <p className="rule-health-summary">
              If your work changed — a new job, a new project — history from
              before it is not neutral, it is misleading. Set a date here and
              baselines ignore everything earlier.{' '}
              <strong>Nothing is deleted:</strong> your timeline is untouched
              and clearing the date restores every comparison.
            </p>
            <div className="engine-slider-row">
              <input
                type="date"
                value={epochDraft}
                disabled={saving}
                onChange={e => setEpochDraft(e.target.value)}
              />
              <button
                className="rule-health-mute"
                disabled={saving || !epochDraft}
                onClick={() => applyEpoch(epochDraft || null)}
              >
                Apply
              </button>
              {prefs.baseline_epoch && (
                <button
                  className="rule-health-mute"
                  disabled={saving}
                  onClick={() => applyEpoch(null)}
                >
                  Clear
                </button>
              )}
            </div>
            {prefs.baseline_epoch && (
              <p className="rule-health-footnote">
                Currently ignoring activity before {prefs.baseline_epoch}.
              </p>
            )}
          </div>

          {/* ---- Evaluation ---- */}
          <div className="engine-control">
            <h4>Is the ordering any good?</h4>
            {!evaluation || evaluation.days_evaluated === 0 ? (
              <p className="rule-health-summary">
                Nothing to measure yet. This fills in once you have applied or
                dismissed cards across a few days — those presses are the
                labels it scores against.
              </p>
            ) : (
              <>
                <p className="rule-health-summary">
                  Scored over {evaluation.days_evaluated} day
                  {evaluation.days_evaluated === 1 ? '' : 's'} and{' '}
                  {evaluation.labelled_cards} judged cards, against reorderings
                  of the same cards. The engine{' '}
                  <strong>
                    {evaluation.beats_random ? 'beats' : 'does not beat'}
                  </strong>{' '}
                  a shuffle, and the learned ranker{' '}
                  <strong>
                    {evaluation.ranker_helps ? 'improves on' : 'does not improve on'}
                  </strong>{' '}
                  the rules alone.
                </p>
                <div className="rule-health-scroll">
                  <table className="rule-health-table">
                    <thead>
                      <tr>
                        <th>Ordering</th>
                        <th className="num">P@{evaluation.k}</th>
                        <th className="num">NDCG@{evaluation.k}</th>
                        <th className="num">MRR</th>
                        <th className="num">Coverage</th>
                        {evaluation.support.identified && (
                          <th className="num">Est. value</th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.values(evaluation.strategies).map(m => (
                        <tr
                          key={m.strategy}
                          className={
                            m.strategy === 'engine' ? undefined : 'rule-health-muted'
                          }
                        >
                          <td>{STRATEGY_LABEL[m.strategy] ?? m.strategy}</td>
                          <td className="num">{pct(m.precision_at_k)}</td>
                          <td className="num">{pct(m.ndcg_at_k)}</td>
                          <td className="num">{pct(m.mrr)}</td>
                          <td className="num">{pct(m.coverage)}</td>
                          {evaluation.support.identified && (
                            <td className="num">{pct(m.off_policy_value)}</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="rule-health-footnote">{evaluation.support.reason}</p>
              </>
            )}
          </div>

          {/* ---- Synthetic ground truth ---- */}
          {simulation && (
            <div className="engine-control">
              <h4>Do the rules detect what they claim to?</h4>
              <p className="rule-health-summary">
                Your feedback says whether a card was <em>wanted</em>, which is
                a different question from whether it was <em>right</em>. These
                days are generated with the condition deliberately planted or
                deliberately withheld, so the correct answer is known before
                the rule runs. Across {simulation.rules} rules:{' '}
                <strong>{pct(simulation.precision)}</strong> precision,{' '}
                <strong>{pct(simulation.recall)}</strong> recall,{' '}
                {simulation.false_positives} false positive
                {simulation.false_positives === 1 ? '' : 's'}.
              </p>

              <div className="rule-health-scroll">
                <table className="rule-health-table">
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th className="num">Detected</th>
                      <th className="num">False alarms</th>
                      <th className="num">Fires at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.values(simulation.per_rule).map(rule => {
                      const curve = simulation.sensitivity[rule.rule_id] ?? {};
                      const turnsOn = Object.keys(curve)
                        .map(Number)
                        .sort((a, b) => a - b)
                        .find(step => curve[String(step)] >= 0.5);
                      return (
                        <tr key={rule.rule_id}>
                          <td>
                            <span className="rule-health-id">{rule.rule_id}</span>
                          </td>
                          <td className="num">
                            {rule.true_positives}/{rule.positives}
                          </td>
                          <td className="num">{rule.false_positives}</td>
                          <td className="num">
                            {turnsOn === undefined ? '—' : `${turnsOn}σ`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <p className="rule-health-footnote">
                "Fires at" is the smallest planted deviation, in standard
                deviations from your median, at which the rule starts speaking
                up. That curve is the evidence for where each threshold sits,
                rather than an assertion that it is right. Reproducible from
                seed {simulation.seed}.
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default EngineControlsPanel;
