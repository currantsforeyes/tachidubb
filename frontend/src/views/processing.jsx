// Processing view — live job stage chain
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useRef } = React;
import { ACTIVE_STATUSES, STAGES, fmtSec, stageForStatus } from '../constants';
import { I } from '../icons';
import { mountSphere } from '../sphere';
import { LongProgress, StatusBadge } from '../ui';

// ═══════════════════════════════════════════════════════════════════
// PROCESSING VIEW — live job progress with stage chain + log tail
// Polls /api/jobs (parent does that) and shows real-time stage/progress.
// Cancel button POSTs to /api/dub/{id}/cancel.
// ═══════════════════════════════════════════════════════════════════
export function ProcessingView({ runningJob, sphereOn, onJobCancelled, onSwitchToHome }) {
  // logTail keeps last N step_detail strings as they change. Server doesn't
  // expose a true log endpoint, but watching `step_detail` mutations gives
  // the user "something is happening" feedback that's faithful to actual progress.
  const [logTail, setLogTail] = useState([]);
  const lastDetailRef = useRef(null);
  const [cancelling, setCancelling] = useState(false);

  // Capture step_detail changes into logTail
  useEffect(() => {
    if (!runningJob) return;
    const detail = runningJob.step_detail;
    if (detail && detail !== lastDetailRef.current) {
      const ts = new Date().toTimeString().slice(0, 8);
      const status = runningJob.status || '';
      setLogTail(prev => [...prev.slice(-15), { ts, status, detail }]);
      lastDetailRef.current = detail;
    }
  }, [runningJob?.step_detail, runningJob?.status]);

  // Reset log tail when we switch to a different job
  useEffect(() => {
    setLogTail([]);
    lastDetailRef.current = null;
  }, [runningJob?.id]);

  const cancel = async () => {
    if (!runningJob || cancelling) return;
    if (!confirm('Cancel this job? In-progress work will be discarded.')) return;
    setCancelling(true);
    try {
      await fetch(`/api/dub/${runningJob.id}/cancel`, { method: 'POST' });
      // Don't navigate immediately — let the next /api/jobs poll show
      // status=cancelled, then user sees the result.
      setTimeout(() => onJobCancelled(), 600);
    } catch (e) {
      alert('Cancel failed: ' + e);
    } finally {
      setCancelling(false);
    }
  };

  // No active job — empty state
  if (!runningJob) {
    return <ProcessingEmpty onSwitchToHome={onSwitchToHome}/>;
  }

  const progress = (runningJob.progress || 0) / 100;
  const stageIdx = stageForStatus(runningJob.status);
  const startedAt = runningJob.started_at || runningJob.created;
  const elapsedSec = startedAt ? Math.floor(Date.now() / 1000 - startedAt) : 0;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* Hero — sphere + headline + big progress */}
      <div style={{
        padding: '32px 40px 28px',
        borderBottom: '1px solid var(--line)',
        display: 'flex', alignItems: 'center', gap: 32,
      }}>
        {sphereOn && <ProcessingSphere/>}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="caps" style={{ marginBottom: 8 }}>
            <span style={{ color: 'var(--accent)' }}>● Live</span>
            <span style={{ marginLeft: 10, color: 'var(--ink-4)' }}>job {runningJob.id?.slice(0, 8)}</span>
          </div>
          <div className="serif" style={{
            fontSize: 28, lineHeight: 1.1, letterSpacing: '-0.01em', marginBottom: 6,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {runningJob.source_label || runningJob.source || runningJob.id}
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--ink-3)', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <StatusBadge status={runningJob.status}/>
            <span style={{ color: 'var(--ink-4)' }}>·</span>
            <span>{runningJob.target_lang ? '→ ' + runningJob.target_lang : ''}</span>
            {runningJob.model && <><span style={{ color: 'var(--ink-4)' }}>·</span><span className="mono">{runningJob.model}</span></>}
            {runningJob.duration && <><span style={{ color: 'var(--ink-4)' }}>·</span><span className="mono">{fmtSec(runningJob.duration)}</span></>}
          </div>

          {/* Big percentage + ETA */}
          <div style={{ marginTop: 18 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
              <span className="serif" style={{ fontSize: 36, fontVariantNumeric: 'tabular-nums', color: 'var(--ink)' }}>
                {(progress * 100).toFixed(0)}<span style={{ fontSize: 18, color: 'var(--ink-3)' }}>%</span>
              </span>
              <span style={{ fontSize: 13, color: 'var(--ink-2)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {runningJob.step_detail || '—'}
              </span>
              <div style={{ flex: 1 }}/>
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', flexShrink: 0 }}>
                running for {Math.floor(elapsedSec / 60)}m {elapsedSec % 60}s
              </span>
            </div>
            <LongProgress value={progress} color="var(--ink-2)" height={4}/>
          </div>
        </div>
      </div>

      {/* Body — stages chain | logs */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Stages chain */}
        <div style={{ flex: 1, padding: '28px 40px', overflow: 'auto' }}>
          <div className="caps" style={{ marginBottom: 16 }}>Pipeline</div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {STAGES.map((s, i) => (
              <StageRow
                key={s.id}
                stage={s}
                idx={i}
                state={i < stageIdx ? 'done' : i === stageIdx ? 'running' : 'pending'}
                stepDetail={i === stageIdx ? runningJob.step_detail : null}
                isLast={i === STAGES.length - 1}
              />
            ))}
          </div>

          {/* Error banner */}
          {runningJob.status === 'error' && runningJob.error && (
            <div style={{
              marginTop: 24, padding: '14px 16px',
              background: 'oklch(0.7 0.2 25 / 0.08)', border: '1px solid oklch(0.7 0.2 25 / 0.3)',
              borderRadius: 8,
            }}>
              <div className="caps" style={{ color: 'var(--err)', marginBottom: 6 }}>Error</div>
              <div className="mono" style={{ fontSize: 11.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
                {runningJob.error}
              </div>
            </div>
          )}
        </div>

        {/* Log tail */}
        <div style={{
          width: 380, borderLeft: '1px solid var(--line)',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            padding: '14px 16px', borderBottom: '1px solid var(--line)',
            display: 'flex', alignItems: 'center',
          }}>
            <div className="caps">Activity</div>
            <div style={{ flex: 1 }}/>
            <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
              {logTail.length} updates
            </span>
          </div>
          <div className="scroll" style={{
            flex: 1, padding: '12px 16px',
            fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.7,
          }}>
            {logTail.length === 0 ? (
              <div style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>
                Waiting for first update…
              </div>
            ) : logTail.map((line, i) => (
              <div key={i} style={{ color: i === logTail.length - 1 ? 'var(--ink-2)' : 'var(--ink-3)' }}>
                <span style={{ color: 'var(--ink-4)' }}>[{line.ts}]</span>{' '}
                <span style={{ color: 'var(--accent)' }}>{line.status}</span>{' '}
                {line.detail}
              </div>
            ))}
            {ACTIVE_STATUSES.has(runningJob.status) && (
              <span style={{
                display: 'inline-block', width: 6, height: 11,
                background: 'var(--accent)', verticalAlign: 'text-bottom',
                animation: 'pulse 1s infinite',
              }}/>
            )}
          </div>
          <div style={{ padding: 14, borderTop: '1px solid var(--line)', display: 'flex', gap: 8 }}>
            <button
              onClick={() => navigator.clipboard?.writeText(logTail.map(l => `[${l.ts}] ${l.status} ${l.detail}`).join('\n'))}
              className="btn" style={{ flex: 1, justifyContent: 'center' }}>
              {I.copy} Copy log
            </button>
            <button
              onClick={cancel}
              disabled={cancelling || !ACTIVE_STATUSES.has(runningJob.status)}
              className="btn"
              style={{
                flex: 1, justifyContent: 'center',
                color: 'var(--err)', borderColor: 'oklch(0.7 0.2 25 / 0.4)',
              }}>
              {I.cancel} {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ProcessingEmpty({ onSwitchToHome }) {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, padding: 40, background: 'var(--bg)' }}>
      <div className="caps">No active job</div>
      <div className="serif" style={{ fontSize: 32, letterSpacing: '-0.015em', textAlign: 'center', maxWidth: 480 }}>
        Nothing to watch <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>yet</span>.
      </div>
      <div style={{ fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 360, lineHeight: 1.5 }}>
        When you start a dub it'll show up here with live stage progress, log tail, and a cancel button.
      </div>
      <button onClick={onSwitchToHome} className="btn btn-primary" style={{ marginTop: 8 }}>
        {I.arrow} Start a new dub
      </button>
    </div>
  );
}

export function ProcessingSphere() {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    return mountSphere(ref.current, { variant: 'live', size: 180 });
  }, []);
  return <div ref={ref} style={{ width: 180, height: 180, flexShrink: 0, pointerEvents: 'none' }}/>;
}

export function StageRow({ stage, idx, state, stepDetail, isLast }) {
  const isDone = state === 'done';
  const isRun = state === 'running';
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 16,
      padding: '14px 0',
      borderBottom: isLast ? 'none' : '1px solid var(--line)',
      opacity: state === 'pending' ? 0.55 : 1,
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: '50%',
        background: isDone ? 'var(--accent)' : 'transparent',
        border: '1.5px solid ' + (isDone ? 'var(--accent)' : isRun ? 'var(--accent)' : 'var(--line-2)'),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: isDone ? '#0a0a0d' : isRun ? 'var(--accent)' : 'var(--ink-4)',
        boxShadow: isRun ? '0 0 12px var(--accent-glow)' : 'none',
        flexShrink: 0,
      }}>
        {isDone ? I.check : <span className="mono" style={{ fontSize: 10, fontWeight: 600 }}>{(idx + 1).toString().padStart(2, '0')}</span>}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <div className="serif" style={{ fontSize: 18 }}>{stage.label}</div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>{stage.hint}</div>
          <div style={{ flex: 1 }}/>
          {isRun && <div className="mono" style={{ fontSize: 11, color: 'var(--accent)', animation: 'pulse 1.4s infinite' }}>active</div>}
          {isDone && <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>done</div>}
        </div>
        {isRun && stepDetail && (
          <div style={{
            marginTop: 8, padding: '8px 10px',
            background: 'var(--bg-1)', border: '1px solid var(--line)',
            borderRadius: 5, fontSize: 11.5, color: 'var(--ink-2)',
          }}>{stepDetail}</div>
        )}
      </div>
    </div>
  );
}

