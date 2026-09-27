// Batch view — grouped queue (quick-test / showcase / file batch)
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useMemo } = React;
import { ACTIVE_STATUSES, LANGS, fmtAge } from '../constants';
import { I } from '../icons';
import { LongProgress, StatusBadge } from '../ui';

// ═══════════════════════════════════════════════════════════════════
// BATCH VIEW — group jobs by batch_id. Active batches at top, completed
// below. Reads from the same /api/jobs poll as History.
// ═══════════════════════════════════════════════════════════════════
export function BatchView({ jobs, onRefresh, onJumpProcessing, onJumpResult, onJumpHome }) {
  // Group jobs by batch_id. Jobs without a batch_id are skipped — they're
  // single-video runs and live in History instead.
  const batches = useMemo(() => {
    const map = new Map();
    for (const j of jobs) {
      const bid = j.batch_id;
      if (!bid) continue;
      if (!map.has(bid)) {
        map.set(bid, {
          id: bid,
          label: j.batch_label || `Batch · ${bid.slice(0, 12)}`,
          created: j.created || 0,
          jobs: [],
        });
      }
      map.get(bid).jobs.push(j);
    }
    // Sort jobs inside each batch by their created time, batches by most-recent
    return Array.from(map.values())
      .map(b => ({
        ...b,
        jobs: [...b.jobs].sort((a, b2) => (a.created || 0) - (b2.created || 0)),
      }))
      .sort((a, b) => (b.created || 0) - (a.created || 0));
  }, [jobs]);

  // Active batch: any with at least one running/queued/scheduled job
  const activeBatches = batches.filter(b => b.jobs.some(j => ACTIVE_STATUSES.has(j.status) || j.status === 'scheduled'));
  const completedBatches = batches.filter(b => !activeBatches.includes(b));

  return (
    <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '36px 36px 80px' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 26, gap: 20 }}>
          <div>
            <div className="caps">Batch</div>
            <div className="serif" style={{ fontSize: 36, lineHeight: 1.05, letterSpacing: '-0.015em', marginTop: 4 }}>
              Many at once, <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>cleanly</span>.
            </div>
            <div style={{ color: 'var(--ink-3)', marginTop: 6, fontSize: 13, maxWidth: 540 }}>
              Group runs scheduled together. Best for overnight queues — set 10 videos, walk away, come back to QA in the morning.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onRefresh} className="btn">{I.refresh} Refresh</button>
            <button onClick={onJumpHome} className="btn btn-primary">{I.plus} New batch</button>
          </div>
        </div>

        {/* Empty state */}
        {batches.length === 0 && (
          <div style={{
            padding: '60px 40px', textAlign: 'center',
            background: 'var(--bg-1)', border: '1px solid var(--line)',
            borderRadius: 12,
          }}>
            <div className="caps" style={{ marginBottom: 8 }}>No batches yet</div>
            <div className="serif" style={{ fontSize: 22, lineHeight: 1.15, marginBottom: 10 }}>
              Queue 5+ videos at once <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>and they appear here</span>.
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-3)', maxWidth: 440, margin: '0 auto 18px', lineHeight: 1.55 }}>
              Switch to "Batch — many videos" on the Home form, drop files or paste a list of URLs, hit Queue.
            </div>
            <button onClick={onJumpHome} className="btn btn-primary">{I.arrow} Set up a batch</button>
          </div>
        )}

        {/* Active */}
        {activeBatches.length > 0 && (
          <div style={{ marginBottom: 36 }}>
            <div className="caps" style={{ marginBottom: 10 }}>Active · {activeBatches.length}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {activeBatches.map(b => {
                const isShowcase = b.jobs.some(j => j.batch_kind === 'showcase');
                const isQuickTest = b.jobs.some(j => j.batch_kind === 'quick_test');
                if (isShowcase)  return <ShowcaseBatchCard key={b.id} batch={b}/>;
                if (isQuickTest) return <QuickTestBatchCard key={b.id} batch={b}/>;
                return <BatchCard key={b.id} batch={b}
                  onJumpProcessing={onJumpProcessing}
                  onJumpResult={onJumpResult}
                  onRefresh={onRefresh}/>;
              })}
            </div>
          </div>
        )}

        {/* Completed */}
        {completedBatches.length > 0 && (
          <div>
            <div className="caps" style={{ marginBottom: 10 }}>Completed · {completedBatches.length}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {completedBatches.map(b => {
                const isShowcase = b.jobs.some(j => j.batch_kind === 'showcase');
                const isQuickTest = b.jobs.some(j => j.batch_kind === 'quick_test');
                if (isShowcase)  return <ShowcaseBatchCard key={b.id} batch={b}/>;
                if (isQuickTest) return <QuickTestBatchCard key={b.id} batch={b}/>;
                return <BatchCard key={b.id} batch={b}
                  onJumpProcessing={onJumpProcessing}
                  onJumpResult={onJumpResult}
                  onRefresh={onRefresh}/>;
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Quick-test batch — comparison grid of N languages ──────────────
export function QuickTestBatchCard({ batch }) {
  const [stitching, setStitching] = useState(false);

  const langName = (code) => {
    const l = LANGS.find(x => x.c === code);
    return l ? l.n : (code || '').toUpperCase();
  };

  const sortedJobs = useMemo(() => {
    return [...batch.jobs].sort(
      (a, b) => (a.batch_position ?? 0) - (b.batch_position ?? 0)
    );
  }, [batch.jobs]);

  const allComplete = sortedJobs.length > 0 &&
    sortedJobs.every(j => j.status === 'complete');

  const stitchToShowcase = async () => {
    setStitching(true);
    try {
      const r = await fetch(`/api/showcase/from_batch/${batch.id}`, { method: 'POST' });
      const d = await r.json();
      if (!d.ok) { alert(d.error || 'Failed to start showcase assembly'); setStitching(false); }
      // On success the batch_kind flips to 'showcase' server-side; the next
      // jobs poll re-renders this as ShowcaseBatchCard automatically.
    } catch (e) {
      alert(String(e.message || e));
      setStitching(false);
    }
  };

  const statusPill = (j) => {
    if (j.status === 'complete') return { c: 'var(--accent)', t: 'done' };
    if (j.status === 'error')    return { c: 'var(--err)',    t: 'error' };
    if (j.status === 'queued')   return { c: 'var(--ink-4)',  t: 'queued' };
    if (j.status === 'scheduled')return { c: 'var(--ink-4)',  t: 'scheduled' };
    return { c: 'var(--warn)', t: j.status || 'running' };
  };

  return (
    <div style={{
      padding: 18, background: 'var(--bg-1)',
      border: '1px solid var(--line)', borderRadius: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <div className="caps">Quick test</div>
        <div className="serif" style={{ fontSize: 18 }}>{batch.label}</div>
        <div style={{ flex: 1 }}/>
        {allComplete && (
          <button
            className="btn btn-primary"
            disabled={stitching}
            onClick={stitchToShowcase}
            style={{ fontSize: 11, padding: '5px 12px' }}>
            {stitching ? 'Stitching…' : '▶ Stitch into showcase'}
          </button>
        )}
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{batch.id}</div>
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
        gap: 12,
      }}>
        {sortedJobs.map(j => {
          const st = statusPill(j);
          const videoUrl = j.status === 'complete'
            ? `/outputs/${j.id}/dubbed_video.mp4`
            : null;
          return (
            <div key={j.id} style={{
              padding: 12, background: 'var(--bg)',
              border: '1px solid var(--line)', borderRadius: 8,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
                  {(j.target_lang || '').toUpperCase()}
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--ink-2)', flex: 1 }}>
                  {langName(j.target_lang)}
                </div>
                <span className="dot" style={{ background: st.c }}/>
                <span className="mono" style={{ fontSize: 9.5, color: st.c }}>{st.t}</span>
              </div>
              {videoUrl ? (
                <>
                  <video src={videoUrl} controls
                         style={{ width: '100%', borderRadius: 4, background: '#000' }}/>
                  <a href={videoUrl} download
                     className="mono"
                     style={{ display: 'block', marginTop: 6, fontSize: 10,
                              color: 'var(--accent)', textDecoration: 'none' }}>
                    ▸ download mp4
                  </a>
                </>
              ) : (
                <div style={{
                  width: '100%', aspectRatio: '16 / 9',
                  background: 'var(--bg-2)', borderRadius: 4,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                    {j.status === 'error' ? (j.error || 'failed') : `${j.progress || 0}%`}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Showcase batch — one stitched multilingual reel + per-lang sources ──
export function ShowcaseBatchCard({ batch }) {
  const [showcase, setShowcase] = useState(null);   // { status, url, manifest, ... }
  const [showSources, setShowSources] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      const r = await fetch(`/api/showcase/${batch.id}/rebuild`, { method: 'POST' });
      const d = await r.json();
      if (d.ok) setShowcase({ status: 'assembling' });  // restart polling
      else alert(d.error || 'Rebuild failed');
    } catch (e) {
      alert(String(e.message || e));
    } finally {
      setRebuilding(false);
    }
  };

  const langName = (code) => {
    const l = LANGS.find(x => x.c === code);
    return l ? l.n : (code || '').toUpperCase();
  };

  const sortedJobs = useMemo(() => (
    [...batch.jobs].sort((a, b) => (a.batch_position ?? 0) - (b.batch_position ?? 0))
  ), [batch.jobs]);

  const done = sortedJobs.filter(j => j.status === 'complete').length;
  const errored = sortedJobs.filter(j => j.status === 'error').length;
  const total = sortedJobs.length;
  const allComplete = done === total && total > 0;

  // Poll the showcase status until it's ready (or errors out)
  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const r = await fetch(`/api/showcase/${batch.id}`);
        if (!live) return;
        if (r.ok) {
          const d = await r.json();
          setShowcase(d);
        } else if (r.status === 500) {
          const d = await r.json().catch(() => ({}));
          setShowcase({ status: 'error', error: d.error || 'Assembly failed' });
        }
      } catch (_) { /* ignore — keep polling */ }
    };
    poll();
    // Poll only while we're waiting for assembly to finish
    if (!showcase || (showcase.status !== 'ready' && showcase.status !== 'error')) {
      const t = setInterval(poll, 3000);
      return () => { live = false; clearInterval(t); };
    }
    return () => { live = false; };
  }, [batch.id, showcase?.status, allComplete]);

  const statusPill = (j) => {
    if (j.status === 'complete') return { c: 'var(--accent)', t: 'done' };
    if (j.status === 'error')    return { c: 'var(--err)',    t: 'error' };
    if (j.status === 'queued')   return { c: 'var(--ink-4)',  t: 'queued' };
    return { c: 'var(--warn)', t: j.status || 'running' };
  };

  const reelUrl = showcase?.status === 'ready'
    ? `${showcase.url}?v=${Math.floor((showcase.manifest?.created || 0))}`
    : null;

  return (
    <div style={{
      padding: 18, background: 'var(--bg-1)',
      border: '1px solid var(--line)', borderRadius: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 14 }}>
        <div className="caps">Showcase reel</div>
        <div className="serif" style={{ fontSize: 18 }}>{batch.label}</div>
        <div style={{ flex: 1 }}/>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{batch.id}</div>
      </div>

      {/* Hero: the stitched reel itself */}
      {reelUrl ? (
        <div style={{ marginBottom: 14 }}>
          <video src={reelUrl} controls
                 style={{ width: '100%', borderRadius: 8, background: '#000', maxHeight: 520 }}/>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
            <a href={reelUrl} download={`showcase_${batch.id}.mp4`}
               className="mono"
               style={{ fontSize: 11, color: 'var(--accent)', textDecoration: 'none' }}>
              ▸ download multilingual reel
            </a>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
              {sortedJobs.length} languages ·{' '}
              {(showcase.manifest?.total_seconds || 0).toFixed(1)}s total
            </div>
          </div>
          {/* Slice manifest — which language plays when */}
          {showcase.manifest?.slices && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
              {showcase.manifest.slices.map((s, i) => (
                <div key={i} style={{
                  padding: '4px 8px', background: 'var(--bg)',
                  border: '1px solid var(--line)', borderRadius: 4,
                  fontSize: 10.5,
                }}>
                  <span className="mono" style={{ color: 'var(--accent)', marginRight: 6 }}>
                    {(s.lang || '').toUpperCase()}
                  </span>
                  <span style={{ color: 'var(--ink-3)' }}>
                    {(s.dub_start ?? s.start ?? 0).toFixed(1)}–{(s.dub_end ?? s.end ?? 0).toFixed(1)}s
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div style={{
          padding: 18, marginBottom: 14,
          background: 'var(--bg)', borderRadius: 8,
          border: '1px dashed var(--line)',
          textAlign: 'center',
        }}>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 6 }}>
            {showcase?.status === 'error' ? 'Stitch step failed' :
             allComplete ? 'Stitching segments into one reel…' :
             `Dubbing ${done}/${total} languages` +
             (errored ? ` · ${errored} errored` : '') + '…'}
          </div>
          {showcase?.status === 'error' && (
            <div className="mono" style={{ fontSize: 10, color: 'var(--err)', whiteSpace: 'pre-wrap', textAlign: 'left' }}>
              {showcase.error}
            </div>
          )}
          <div style={{
            height: 6, background: 'var(--bg-2)', borderRadius: 3,
            overflow: 'hidden', maxWidth: 320, margin: '8px auto 0',
          }}>
            <div style={{
              height: '100%',
              width: `${total ? (done / total) * 100 : 0}%`,
              background: 'var(--accent)',
              transition: 'width 0.5s ease',
            }}/>
          </div>
          {allComplete && (
            <button
              className="btn btn-primary"
              disabled={rebuilding}
              onClick={rebuild}
              style={{ marginTop: 12, fontSize: 11 }}>
              {rebuilding ? 'Rebuilding…' : '↻ Rebuild showcase reel'}
            </button>
          )}
        </div>
      )}

      {/* Collapsible: per-language source dubs */}
      <div>
        <button className="btn-ghost"
                onClick={() => setShowSources(v => !v)}
                style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          {showSources ? '▾' : '▸'} Individual language dubs ({total})
        </button>
        {showSources && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 12, marginTop: 10,
          }}>
            {sortedJobs.map(j => {
              const st = statusPill(j);
              const videoUrl = j.status === 'complete'
                ? `/outputs/${j.id}/dubbed_video.mp4`
                : null;
              return (
                <div key={j.id} style={{
                  padding: 12, background: 'var(--bg)',
                  border: '1px solid var(--line)', borderRadius: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
                      {(j.target_lang || '').toUpperCase()}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--ink-2)', flex: 1 }}>
                      {langName(j.target_lang)}
                    </div>
                    <span className="dot" style={{ background: st.c }}/>
                    <span className="mono" style={{ fontSize: 9.5, color: st.c }}>{st.t}</span>
                  </div>
                  {videoUrl ? (
                    <video src={videoUrl} controls
                           style={{ width: '100%', borderRadius: 4, background: '#000' }}/>
                  ) : (
                    <div style={{
                      width: '100%', aspectRatio: '16 / 9',
                      background: 'var(--bg-2)', borderRadius: 4,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                        {j.status === 'error' ? (j.error || 'failed') : `${j.progress || 0}%`}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function BatchCard({ batch, onJumpProcessing, onJumpResult, onRefresh }) {
  const [expanded, setExpanded] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const total = batch.jobs.length;
  const done = batch.jobs.filter(j => j.status === 'complete').length;
  const errored = batch.jobs.filter(j => j.status === 'error').length;
  const running = batch.jobs.filter(j => ACTIVE_STATUSES.has(j.status) && j.status !== 'queued').length;
  const queued = batch.jobs.filter(j => j.status === 'queued' || j.status === 'scheduled').length;

  const allDone = done + errored === total && total > 0;
  const pct = total > 0 ? done / total : 0;

  // ETA — if any job is running, take its progress + remaining queued count and
  // multiply by the average completed-job duration. Rough but useful.
  const eta = useMemo(() => {
    if (allDone || running === 0) return null;
    const completedJobs = batch.jobs.filter(j => j.status === 'complete' && j.completed_at && j.started_at);
    if (completedJobs.length === 0) return null;
    const avgSec = completedJobs.reduce((sum, j) => sum + (j.completed_at - j.started_at), 0) / completedJobs.length;
    const remaining = queued + running;
    return Math.round(remaining * avgSec);
  }, [batch.jobs, queued, running, allDone]);

  const cancelBatch = async () => {
    const pendingIds = batch.jobs.filter(j => ACTIVE_STATUSES.has(j.status) || j.status === 'scheduled').map(j => j.id);
    if (pendingIds.length === 0) { onRefresh(); return; }
    if (!confirm(`Cancel ${pendingIds.length} pending job(s) in this batch?`)) return;
    setCancelling(true);
    try {
      // Issue cancels in parallel
      await Promise.all(pendingIds.map(id => fetch(`/api/dub/${id}/cancel`, { method: 'POST' })));
      onRefresh();
    } finally { setCancelling(false); }
  };

  return (
    <div style={{
      background: 'var(--bg-1)',
      border: '1px solid ' + (running > 0 ? 'var(--accent-dim)' : 'var(--line)'),
      borderRadius: 10, overflow: 'hidden',
    }}>
      {/* Summary row */}
      <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'flex-start', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            {running > 0 && <span className="dot" style={{ background: 'var(--accent)', boxShadow: '0 0 5px var(--accent-glow)', animation: 'pulse 1.5s infinite' }}/>}
            {allDone && errored === 0 && <span className="dot" style={{ background: 'var(--accent)' }}/>}
            {allDone && errored > 0 && <span className="dot" style={{ background: 'var(--warn)' }}/>}
            {!running && !allDone && <span className="dot" style={{ background: '#8a9aff' }}/>}
            <div className="serif" style={{ fontSize: 19, color: 'var(--ink)' }}>{batch.label}</div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span><span className="mono" style={{ color: 'var(--ink-2)' }}>{done}</span>/{total} done</span>
            {running > 0 && <span><span className="mono" style={{ color: 'var(--accent)' }}>{running}</span> running</span>}
            {queued > 0 && <span><span className="mono" style={{ color: 'var(--ink-2)' }}>{queued}</span> queued</span>}
            {errored > 0 && <span style={{ color: 'var(--err)' }}><span className="mono">{errored}</span> failed</span>}
            {eta != null && <><span style={{ color: 'var(--ink-4)' }}>·</span><span>ETA {Math.round(eta / 60)}m</span></>}
            <span style={{ color: 'var(--ink-4)' }}>·</span>
            <span>{fmtAge(batch.created)}</span>
          </div>
          {/* Aggregate progress */}
          <div style={{ marginTop: 12, maxWidth: 480 }}>
            <LongProgress value={pct} color={running > 0 ? 'var(--accent)' : 'var(--ink-2)'} height={3}/>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          {running > 0 && (
            <button onClick={onJumpProcessing} className="btn">{I.eye} Watch</button>
          )}
          {(running > 0 || queued > 0) && (
            <button onClick={cancelBatch} disabled={cancelling} className="btn" style={{ color: 'var(--err)', borderColor: 'oklch(0.7 0.2 25 / 0.4)' }}>
              {I.cancel} {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
          <button onClick={() => setExpanded(!expanded)} className="btn">
            {expanded ? 'Hide' : 'Show'} jobs
          </button>
        </div>
      </div>

      {/* Expandable per-job list */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--line)', background: 'var(--bg)' }}>
          {batch.jobs.map(j => (
            <BatchJobRow
              key={j.id} job={j}
              onJumpProcessing={onJumpProcessing}
              onJumpResult={onJumpResult}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function BatchJobRow({ job, onJumpProcessing, onJumpResult }) {
  const isRunning = ACTIVE_STATUSES.has(job.status) && job.status !== 'queued';
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '30px 2.4fr 1fr 1fr 100px',
      padding: '10px 20px', gap: 12, alignItems: 'center',
      borderBottom: '1px solid var(--line)',
      background: isRunning ? 'oklch(0.88 0.18 125 / 0.03)' : 'transparent',
    }}>
      <div style={{
        width: 22, height: 22, borderRadius: '50%',
        background: job.status === 'complete' ? 'var(--accent)' : 'transparent',
        border: '1.5px solid ' + (
          job.status === 'complete' ? 'var(--accent)'
          : isRunning ? 'var(--accent)'
          : job.status === 'error' ? 'var(--err)'
          : 'var(--line-2)'
        ),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: job.status === 'complete' ? '#0a0a0d' : isRunning ? 'var(--accent)' : 'var(--ink-4)',
        boxShadow: isRunning ? '0 0 8px var(--accent-glow)' : 'none',
        flexShrink: 0,
      }}>
        {job.status === 'complete'
          ? <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2.5 6.5l2.5 2.5 5-6"/></svg>
          : null
        }
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {job.source_label || job.source || job.id}
        </div>
        {job.error && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {job.error}
          </div>
        )}
      </div>
      <div>
        <StatusBadge status={job.status}/>
      </div>
      <div>
        {isRunning && (
          <div>
            <LongProgress value={(job.progress || 0) / 100} color="var(--accent)" height={2}/>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
              {(job.progress || 0).toFixed(0)}% · {job.step_detail?.slice(0, 30) || job.status}
            </div>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
        {job.status === 'complete' && (
          <button onClick={() => onJumpResult(job.id)} className="btn" style={{ padding: '3px 8px', fontSize: 11 }}>
            {I.eye} View
          </button>
        )}
        {isRunning && (
          <button onClick={onJumpProcessing} className="btn" style={{ padding: '3px 8px', fontSize: 11 }}>
            {I.eye} Watch
          </button>
        )}
      </div>
    </div>
  );
}

