// Left rail + top bar chrome
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
import { I } from './icons';

// ═══════════════════════════════════════════════════════════════════
// LEFT RAIL — primary navigation (views, not stages)
// ═══════════════════════════════════════════════════════════════════
export function LeftRail({ view, setView, runningJob, awaitingReviewCount, system }) {
  const sections = [
    { id: 'home',        label: 'Home',         hint: 'Upload · queue',       ic: I.home },
    { id: 'editor',      label: 'Editor',       hint: 'Video · dialogue timing', ic: I.edit },
    { id: 'processing',  label: 'Processing',   hint: runningJob ? 'Live job' : 'Idle', ic: I.processing, badge: runningJob ? '●' : null },
    { id: 'review',      label: 'Review',       hint: awaitingReviewCount > 0 ? 'Wizard pause' : 'Nothing pending', ic: I.review, badge: awaitingReviewCount > 0 ? String(awaitingReviewCount) : null },
    { id: 'result',      label: 'Result',       hint: 'Last completed',       ic: I.result },
    { id: 'history',     label: 'History',      hint: 'All jobs',             ic: I.history },
    { id: 'batch',       label: 'Batch',        hint: 'Queue & scheduled',    ic: I.batch },
    { id: 'voices',      label: 'Voices',       hint: 'Library · clone refs', ic: I.voice || I.review },
    { id: 'glossary',    label: 'Glossary',     hint: 'Translation overrides',ic: I.glossary || I.edit },
  ];

  // GPU info from /api/system response. Server returns vram_gb (total)
  // + vram_free_gb (free); we compute "used" as a derived value.
  const vramTotal = system?.gpu?.vram_gb;
  const vramFree = system?.gpu?.vram_free_gb;
  const vramUsed = (vramTotal != null && vramFree != null) ? Math.max(0, vramTotal - vramFree) : null;
  const gpuName = system?.gpu?.name || 'GPU';
  const torchOk = system?.gpu?.ok ?? null;

  return (
    <aside style={{
      width: 232, background: 'var(--bg)',
      borderRight: '1px solid var(--line)',
      display: 'flex', flexDirection: 'column', flexShrink: 0,
    }}>
      {/* Brand */}
      <div style={{ padding: '20px 20px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 24, height: 24, borderRadius: 6, background: 'var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 18px var(--accent-glow)',
          }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#0a0a0d" strokeWidth="1.6"><path d="M2 6c0-1.5.8-2.5 2-2.5s2 1 2 2.5-.8 2.5-2 2.5"/><path d="M6 6c0-1.5.8-2.5 2-2.5s2 1 2 2.5"/></svg>
          </div>
          <div>
            <div className="serif" style={{ fontSize: 19, lineHeight: 1, letterSpacing: '-0.02em' }}>TachiDUBB</div>
            <div className="mono" style={{ color: 'var(--ink-4)', fontSize: 9, marginTop: 3 }}>studio</div>
          </div>
        </div>
      </div>

      {/* Primary nav */}
      <div style={{ padding: '0 12px', flex: 1, overflow: 'auto' }}>
        <div className="caps" style={{ margin: '0 8px 8px' }}>Workspace</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {sections.map(s => <NavItem key={s.id} item={s} active={view === s.id} onClick={() => setView(s.id)}/>)}
        </div>

        <div className="caps" style={{ margin: '20px 8px 8px' }}>System</div>
        <NavItem
          item={{ id: 'system', label: 'System', hint: torchOk === false ? 'Torch broken!' : 'GPU · models · storage', ic: I.system }}
          active={view === 'system'}
          onClick={() => setView('system')}
          warn={torchOk === false}
        />
      </div>

      {/* GPU footer */}
      <div style={{ padding: 12, borderTop: '1px solid var(--line)' }}>
        <div style={{ padding: 10, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{ color: 'var(--ink-3)' }}>{I.cpu}</span>
            <span className="mono" style={{ fontSize: 10, color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {gpuName.replace(/^NVIDIA /, '').slice(0, 18)}
            </span>
            <div style={{ flex: 1 }}/>
            <span className="dot" style={{ background: torchOk === false ? 'var(--err)' : 'var(--accent)', boxShadow: torchOk === false ? 'none' : '0 0 6px var(--accent-glow)' }}/>
          </div>
          {vramTotal ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <span className="serif" style={{ fontSize: 16 }}>{vramUsed?.toFixed(1) ?? '—'}</span>
                <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>/ {vramTotal} GB · VRAM</span>
              </div>
              <div style={{ height: 2, background: 'var(--bg-3)', borderRadius: 1, marginTop: 6, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${Math.min(100, (vramUsed / vramTotal) * 100)}%`, background: 'var(--accent)', opacity: 0.7 }}/>
              </div>
            </>
          ) : (
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>Loading…</div>
          )}
        </div>
        <div style={{ padding: '8px 12px 4px', borderTop: '1px solid var(--line)', textAlign: 'center' }}>
          <div className="mono" style={{ fontSize: 9, color: 'var(--ink-4)', lineHeight: 1.6 }}>
            TachikomaRed &amp; smolemaru
          </div>
        </div>
      </div>
    </aside>
  );
}

export function NavItem({ item, active, onClick, warn }) {
  return (
    <button onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '9px 10px', borderRadius: 6,
      background: active ? 'var(--bg-2)' : 'transparent',
      border: '1px solid ' + (active ? 'var(--line-2)' : 'transparent'),
      color: active ? 'var(--ink)' : 'var(--ink-2)',
      textAlign: 'left', transition: 'all 0.12s',
    }}>
      <div style={{
        width: 22, height: 22, borderRadius: 5,
        background: active ? 'var(--bg-3)' : 'var(--bg-1)',
        border: '1px solid ' + (active ? 'var(--line-2)' : 'var(--line)'),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: warn ? 'var(--err)' : (active ? 'var(--accent)' : 'var(--ink-3)'),
        flexShrink: 0,
      }}>{item.ic}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: active ? 500 : 400 }}>{item.label}</div>
        <div className="mono" style={{ color: warn ? 'var(--err)' : 'var(--ink-4)', fontSize: 10, marginTop: 1 }}>{item.hint}</div>
      </div>
      {item.badge && (
        <span style={{
          fontSize: 9, color: item.badge === '●' ? 'var(--accent)' : 'var(--ink-3)',
          fontFamily: 'var(--mono)', padding: '2px 5px', borderRadius: 4,
          background: item.badge === '●' ? 'transparent' : 'var(--bg-2)',
          border: item.badge === '●' ? 'none' : '1px solid var(--line)',
          animation: item.badge === '●' ? 'pulse 1.5s infinite' : 'none',
        }}>{item.badge}</span>
      )}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════════
// TOP BAR — context-aware. Running pill, awaiting-review pill, search.
// ═══════════════════════════════════════════════════════════════════
export function TopBar({ view, runningJob, awaitingReviewCount, onJumpToProcessing, onJumpToReview }) {
  const TITLES = {
    home: 'Home', editor: 'Editor · dialogue timing', processing: 'Processing', review: 'Review · wizard pause',
    result: 'Result', history: 'History', batch: 'Batch queue', system: 'System',
  };
  // Server returns progress 0-100. Normalize to 0-1 for UI math.
  const overall = (runningJob?.progress ?? 0) / 100;
  const eta = runningJob?.eta_seconds ?? null;

  return (
    <div style={{
      height: 50, borderBottom: '1px solid var(--line)',
      display: 'flex', alignItems: 'center',
      padding: '0 22px', gap: 12, background: 'var(--bg)', flexShrink: 0,
    }}>
      <div className="serif" style={{ fontSize: 17, letterSpacing: '-0.01em' }}>{TITLES[view] || 'TachiDUBB Studio'}</div>
      {view === 'processing' && runningJob && (
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>
          · {(runningJob.source_label || runningJob.source || runningJob.id).slice(0, 50)}
        </span>
      )}
      <div style={{ flex: 1 }}/>

      {/* Running job pill — clickable, follows you across views */}
      {runningJob && view !== 'processing' && (
        <button onClick={onJumpToProcessing} className="chip" style={{ color: 'var(--ink-2)', cursor: 'pointer' }}>
          <span className="dot" style={{ background: 'var(--accent)', boxShadow: '0 0 5px var(--accent-glow)', animation: 'pulse 1.5s infinite' }}/>
          <span>Running · {(overall * 100).toFixed(0)}%</span>
          {eta != null && <span className="mono" style={{ color: 'var(--ink-4)' }}>· ETA {Math.round(eta / 60)}m</span>}
        </button>
      )}

      {/* Awaiting review pill */}
      {awaitingReviewCount > 0 && view !== 'review' && (
        <button onClick={onJumpToReview} className="chip" style={{
          color: 'var(--warn)', borderColor: 'var(--warn)',
          background: 'oklch(0.78 0.15 60 / 0.1)', cursor: 'pointer',
        }}>
          {I.review} {awaitingReviewCount} awaiting review
        </button>
      )}
    </div>
  );
}

