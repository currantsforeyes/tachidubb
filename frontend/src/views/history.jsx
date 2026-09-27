// History view — job table with filter/search/star
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useMemo } = React;
import { ACTIVE_STATUSES, LANGS, fmtAge, fmtSec } from '../constants';
import { I } from '../icons';
import { LongProgress, StatusBadge } from '../ui';

// ═══════════════════════════════════════════════════════════════════
// HISTORY VIEW — table of all jobs with filter/search/star + actions.
// Jobs come from parent App's poll.
// ═══════════════════════════════════════════════════════════════════
export function HistoryView({ jobs, onJumpProcessing, onJumpReview, onJumpResult, onRefresh }) {
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [starOnly, setStarOnly] = useState(false);

  const filtered = useMemo(() => {
    return jobs.filter(j => {
      if (starOnly && !j.starred) return false;
      if (filter === 'all') {
        // ok
      } else if (filter === 'active') {
        if (!ACTIVE_STATUSES.has(j.status)) return false;
      } else if (filter === 'review') {
        if (j.status !== 'awaiting_translation_review' && j.status !== 'awaiting_transcript_review') return false;
      } else if (j.status !== filter) {
        return false;
      }
      if (q) {
        const hay = (j.source_label || j.source || j.id || '').toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [jobs, q, filter, starOnly]);

  const counts = useMemo(() => {
    const c = { all: jobs.length, active: 0, review: 0, complete: 0, error: 0 };
    for (const j of jobs) {
      if (ACTIVE_STATUSES.has(j.status)) c.active++;
      if (j.status === 'awaiting_translation_review' || j.status === 'awaiting_transcript_review') c.review++;
      if (j.status === 'complete') c.complete++;
      if (j.status === 'error' || j.status === 'cancelled') c.error++;
    }
    return c;
  }, [jobs]);

  return (
    <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '36px 36px 80px' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 26, gap: 20 }}>
          <div>
            <div className="caps">History</div>
            <div className="serif" style={{ fontSize: 36, lineHeight: 1.05, letterSpacing: '-0.015em', marginTop: 4 }}>
              Every run, <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>kept</span>.
            </div>
            <div style={{ color: 'var(--ink-3)', marginTop: 6, fontSize: 13, maxWidth: 520 }}>
              Starred jobs are protected from storage cleanup. Click a row's actions to view, resume, or open its folder.
            </div>
          </div>
          <button onClick={onRefresh} className="btn">
            {I.refresh} Refresh
          </button>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: 1, maxWidth: 340 }}>
            <div style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-3)' }}>
              {I.search}
            </div>
            <input
              className="field"
              placeholder="Search by title, URL, ID…"
              value={q}
              onChange={e => setQ(e.target.value)}
              style={{ paddingLeft: 32 }}
            />
          </div>

          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {[
              ['all',      'All',        counts.all],
              ['active',   'Active',     counts.active],
              ['review',   'In review',  counts.review],
              ['complete', 'Complete',   counts.complete],
              ['error',    'Error',      counts.error],
            ].map(([id, label, count]) => (
              <button key={id} onClick={() => setFilter(id)} className="btn" style={{
                padding: '5px 10px', fontSize: 11,
                borderColor: filter === id ? 'var(--accent)' : 'var(--line)',
                background: filter === id ? 'var(--accent-dim)' : 'var(--bg-1)',
                color: filter === id ? 'var(--accent)' : 'var(--ink-2)',
              }}>
                {label} {count > 0 && <span className="mono" style={{ marginLeft: 4, opacity: 0.6, fontSize: 10 }}>{count}</span>}
              </button>
            ))}
          </div>

          <div style={{ flex: 1 }}/>

          <button onClick={() => setStarOnly(!starOnly)} className="btn" style={{
            padding: '5px 10px', fontSize: 11,
            borderColor: starOnly ? '#e6c454' : 'var(--line)',
            color: starOnly ? '#e6c454' : 'var(--ink-2)',
          }}>
            {starOnly ? I.star : I.starOff}
            Starred only
          </button>
        </div>

        {/* Table */}
        <div style={{ border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden', background: 'var(--bg-1)' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '30px 2.4fr 1fr 0.9fr 0.9fr 200px',
            padding: '10px 16px',
            borderBottom: '1px solid var(--line)',
            background: 'var(--bg-2)', gap: 12,
          }}>
            {['', 'Title', 'Status', 'Duration', 'Age', ''].map((h, i) => (
              <div key={i} className="caps">{h}</div>
            ))}
          </div>
          {filtered.length === 0 ? (
            <div style={{ padding: '64px 20px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 12 }}>
              {jobs.length === 0
                ? <>No jobs yet. <span style={{ color: 'var(--ink-4)' }}>Start your first dub from Home →</span></>
                : <>No jobs match the filter. <button className="btn" style={{ marginLeft: 8 }} onClick={() => { setQ(''); setFilter('all'); setStarOnly(false); }}>Reset</button></>
              }
            </div>
          ) : filtered.map(job => (
            <JobRow
              key={job.id}
              job={job}
              onJumpProcessing={onJumpProcessing}
              onJumpReview={onJumpReview}
              onJumpResult={onJumpResult}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function JobRow({ job, onJumpProcessing, onJumpReview, onJumpResult, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [redubOpen, setRedubOpen] = useState(false);

  const star = async () => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('starred', job.starred ? 'false' : 'true');
      await fetch(`/api/storage/star/${job.id}`, { method: 'POST', body: fd });
      onRefresh();
    } finally { setBusy(false); }
  };

  const cancel = async () => {
    if (!confirm('Cancel this job?')) return;
    setBusy(true);
    try {
      await fetch(`/api/dub/${job.id}/cancel`, { method: 'POST' });
      onRefresh();
    } finally { setBusy(false); }
  };

  const resume = async () => {
    setBusy(true);
    try {
      // Continue from latest checkpoint
      const fd = new FormData();
      const r = await fetch(`/api/dub/${job.id}/continue`, { method: 'POST', body: fd });
      if (r.ok) {
        onRefresh();
        onJumpProcessing();
      } else {
        alert('Resume failed');
      }
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!confirm('Delete this job and its files?')) return;
    setBusy(true);
    try {
      await fetch(`/api/job/${job.id}`, { method: 'DELETE' });
      onRefresh();
    } finally { setBusy(false); }
  };

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '30px 2.4fr 1fr 0.9fr 0.9fr 200px',
      padding: '12px 16px',
      borderBottom: '1px solid var(--line)',
      alignItems: 'center', gap: 12,
      transition: 'background 0.12s',
    }}
    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
    >
      <button className="btn-ghost" disabled={busy}
        style={{ padding: 4, color: job.starred ? '#e6c454' : 'var(--ink-4)' }}
        onClick={star}
        title={job.starred ? 'Unstar' : 'Star (protect from cleanup)'}
      >
        {job.starred ? I.star : I.starOff}
      </button>

      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {job.source_label || job.source || job.id}
        </div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span>{job.id?.slice(0, 8)}</span>
          {job.target_lang && <span>· → {job.target_lang}</span>}
          {job.model && <span>· {job.model}</span>}
          {job.batch_label && <span style={{ color: 'var(--accent)' }}>· {job.batch_label}</span>}
        </div>
        {job.error && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {I.cancel} {job.error}
          </div>
        )}
      </div>

      <div>
        <StatusBadge status={job.status}/>
        {ACTIVE_STATUSES.has(job.status) && (
          <div style={{ marginTop: 5, width: 110 }}>
            <LongProgress value={(job.progress || 0) / 100} color="var(--accent)" height={2}/>
          </div>
        )}
      </div>

      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>
        {job.duration ? fmtSec(job.duration) : '—'}
      </div>

      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>
        {fmtAge(job.created)}
      </div>

      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
        <RowActions
          job={job} busy={busy}
          onView={() => onJumpResult(job.id)}
          onWatch={() => onJumpProcessing()}
          onReview={() => onJumpReview(job.id)}
          onResume={resume}
          onCancel={cancel}
          onRemove={remove}
          onRedub={() => setRedubOpen(true)}
        />
      </div>
      {redubOpen && (
        <RedubModal
          job={job}
          onClose={() => setRedubOpen(false)}
          onSubmitted={() => { setRedubOpen(false); onRefresh(); }}
        />
      )}
    </div>
  );
}

// ── Re-dub modal — pick new languages + mode, reuses original source ──
export function RedubModal({ job, onClose, onSubmitted }) {
  const pickable = LANGS.filter(l => l.c !== 'auto' && l.c !== job.target_lang);
  const [picked, setPicked] = useState(['fr', 'de']);
  const [mode, setMode] = useState('compare');      // 'single' | 'compare' | 'showcase'
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const toggle = (c) => {
    if (picked.includes(c)) {
      if (mode === 'single' || picked.length > 1) setPicked(picked.filter(x => x !== c));
    } else {
      if (mode === 'single') setPicked([c]);
      else if (picked.length < 6) setPicked([...picked, c]);
    }
  };

  // Constrain picked count when mode changes
  useEffect(() => {
    if (mode === 'single' && picked.length > 1) setPicked([picked[0]]);
    if (mode !== 'single' && picked.length < 2) setPicked([...picked, 'de'].slice(0, 2));
  }, [mode]);

  const canSubmit = !busy && (
    (mode === 'single' && picked.length === 1) ||
    (mode !== 'single' && picked.length >= 2 && picked.length <= 6)
  );

  const submit = async () => {
    setError(null); setBusy(true);
    try {
      const fd = new FormData();
      fd.append('target_langs', picked.join(','));
      fd.append('mode', mode);
      const r = await fetch(`/api/job/${job.id}/redub`, { method: 'POST', body: fd });
      const d = await r.json();
      if (d.ok) onSubmitted();
      else setError(d.error || 'Re-dub failed');
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(560px, 92vw)', background: 'var(--bg-1)',
        border: '1px solid var(--line)', borderRadius: 10, padding: 22,
      }}>
        <div className="caps" style={{ marginBottom: 6 }}>Re-dub from history</div>
        <div className="serif" style={{ fontSize: 20, marginBottom: 4 }}>
          {job.source_label || job.id}
        </div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginBottom: 18 }}>
          original → {job.target_lang?.toUpperCase()} · {job.model || '—'}
        </div>

        {/* Mode toggle */}
        <div className="caps" style={{ marginBottom: 8 }}>Mode</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 18 }}>
          {[
            { id: 'single',   t: 'Single', d: 'One new dub' },
            { id: 'compare',  t: 'Compare', d: 'N separate dubs (2–6)' },
            { id: 'showcase', t: 'Showcase', d: 'Stitched reel' },
          ].map(o => (
            <button key={o.id}
              className={'btn ' + (mode === o.id ? 'btn-primary' : '')}
              onClick={() => setMode(o.id)}
              style={{ flex: 1, padding: '8px 6px', flexDirection: 'column', alignItems: 'center', display: 'flex', gap: 2 }}>
              <div style={{ fontSize: 12 }}>{o.t}</div>
              <div style={{ fontSize: 9.5, color: mode === o.id ? 'inherit' : 'var(--ink-4)' }}>{o.d}</div>
            </button>
          ))}
        </div>

        {/* Language chips */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
          <div className="caps">Target languages · {picked.length} {mode === 'single' ? '' : 'of 2–6'}</div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
          {pickable.map(l => {
            const on = picked.includes(l.c);
            const disabled = !on && mode !== 'single' && picked.length >= 6;
            return (
              <button key={l.c} onClick={() => toggle(l.c)} disabled={disabled}
                style={{
                  padding: '6px 10px', borderRadius: 4,
                  background: on ? 'var(--accent)' : 'var(--bg)',
                  color: on ? '#0a0a0d' : 'var(--ink-2)',
                  border: '1px solid ' + (on ? 'var(--accent)' : 'var(--line)'),
                  fontSize: 11.5, cursor: disabled ? 'not-allowed' : 'pointer',
                  opacity: disabled ? 0.4 : 1,
                }}>
                {l.n}
              </button>
            );
          })}
        </div>

        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginBottom: 16, lineHeight: 1.6 }}>
          Settings inherited from the original (voice preset, model, whisper, TTS speed, etc).
          Source video is reused — no re-upload.
        </div>

        {error && (
          <div className="mono" style={{ fontSize: 11, color: 'var(--err)', marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={!canSubmit}>
            {busy ? 'Queuing…' :
              mode === 'single' ? `Re-dub in ${picked[0]?.toUpperCase() || '?'}` :
              mode === 'showcase' ? `Build showcase · ${picked.length} langs` :
              `Queue ${picked.length} dubs`}
          </button>
        </div>
      </div>
    </div>
  );
}

export function RowActions({ job, busy, onView, onWatch, onReview, onResume, onCancel, onRemove, onRedub }) {
  if (job.status === 'complete') {
    return (
      <>
        <button className="btn" disabled={busy} onClick={onView} style={{ padding: '4px 10px', fontSize: 11 }}>
          {I.eye} View
        </button>
        <button className="btn-ghost" disabled={busy} onClick={onRedub}
                style={{ padding: '4px 8px', fontSize: 11, color: 'var(--ink-3)' }}
                title="Re-dub the same source in new languages">
          ↻ Re-dub
        </button>
      </>
    );
  }
  if (job.status === 'awaiting_translation_review' || job.status === 'awaiting_transcript_review') {
    return (
      <button className="btn btn-primary" disabled={busy} onClick={onReview} style={{ padding: '4px 10px', fontSize: 11 }}>
        {I.edit} Review
      </button>
    );
  }
  if (job.status === 'error' || job.status === 'cancelled') {
    return (
      <>
        {job.has_checkpoint && (
          <button className="btn" disabled={busy} onClick={onResume} style={{ padding: '4px 10px', fontSize: 11 }}>
            {I.refresh} Resume
          </button>
        )}
        <button className="btn-ghost" disabled={busy} onClick={onRemove} style={{ padding: 4, color: 'var(--err)' }} title="Delete">
          {I.trash}
        </button>
      </>
    );
  }
  if (ACTIVE_STATUSES.has(job.status)) {
    return (
      <>
        <button className="btn" disabled={busy} onClick={onWatch} style={{ padding: '4px 10px', fontSize: 11 }}>
          {I.eye} Watch
        </button>
        <button className="btn-ghost" disabled={busy} onClick={onCancel} style={{ padding: 4, color: 'var(--err)' }} title="Cancel">
          {I.cancel}
        </button>
      </>
    );
  }
  if (job.status === 'scheduled' || job.status === 'queued') {
    return (
      <button className="btn-ghost" disabled={busy} onClick={onCancel} style={{ padding: 4, color: 'var(--err)' }} title="Cancel before start">
        {I.cancel}
      </button>
    );
  }
  return null;
}

