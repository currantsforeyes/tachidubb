// Shared widgets (designer set) + FileSlot drop zone
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useRef } = React;
import { ACTIVE_STATUSES, STATUS_META } from './constants';
import { I } from './icons';

// ═══════════════════════════════════════════════════════════════════
// SHARED WIDGETS (designer's set, condensed)
// ═══════════════════════════════════════════════════════════════════
export function Toggle({ value, onChange, label, hint, disabled = false }) {
  const handle = () => { if (!disabled) onChange(!value); };
  return (
    <label style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      cursor: disabled ? 'not-allowed' : 'pointer',
      padding: '8px 0',
      opacity: disabled ? 0.5 : 1,
    }}>
      <div onClick={handle} style={{
        width: 30, height: 16, borderRadius: 8,
        background: value ? 'var(--accent)' : 'var(--bg-3)',
        position: 'relative', transition: 'background 0.15s',
        border: '1px solid ' + (value ? 'var(--accent)' : 'var(--line-2)'),
        flexShrink: 0, marginTop: 1,
      }}>
        <div style={{
          position: 'absolute', top: 1, left: value ? 14 : 1,
          width: 12, height: 12, borderRadius: '50%',
          background: value ? '#0a0a0d' : 'var(--ink-2)',
          transition: 'left 0.15s',
        }}/>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--ink)' }}>{label}</div>
        {hint && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2, lineHeight: 1.45 }}>{hint}</div>}
      </div>
    </label>
  );
}

export function Field({ label, hint, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {label && <div className="caps">{label}</div>}
      {children}
      {hint && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 1 }}>{hint}</div>}
    </div>
  );
}

export function Select({ value, onChange, children }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} className="field" style={{
      cursor: 'pointer', appearance: 'none', paddingRight: 28,
      backgroundImage: "url(\"data:image/svg+xml,%3Csvg width='10' height='10' viewBox='0 0 10 10' fill='none'%3E%3Cpath d='M2 4l3 3 3-3' stroke='%235a5a63' stroke-width='1.2'/%3E%3C/svg%3E\")",
      backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center',
    }}>{children}</select>
  );
}

export function SectionHeader({ index, title, subtitle }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, padding: '32px 0 14px', borderBottom: '1px solid var(--line)', marginBottom: 18 }}>
      {index !== undefined && (
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }}>{index.toString().padStart(2, '0')}</span>
      )}
      <div className="serif" style={{ fontSize: 28, lineHeight: 1, letterSpacing: '-0.01em' }}>{title}</div>
      {subtitle && <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>· {subtitle}</span>}
    </div>
  );
}

export function StatusBadge({ status }) {
  const m = STATUS_META[status] || { color: 'var(--ink-3)', label: status };
  const pulse = ACTIVE_STATUSES.has(status);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '3px 8px', borderRadius: 999,
      border: '1px solid ' + m.color + '40',
      background: m.color + '14', color: m.color,
      fontSize: 11, fontWeight: 500,
      animation: pulse ? 'pulse 1.4s infinite' : 'none',
    }}>
      <span className="dot" style={{ background: m.color }}/>
      {m.label}
    </span>
  );
}

// Slim horizontal progress bar — used in headers, footers, anywhere a
// 0-100% needs to be shown without taking vertical space.
export function LongProgress({ value, color = 'var(--accent)', height = 3 }) {
  const v = Math.max(0, Math.min(1, value || 0));
  return (
    <div style={{ height, background: 'var(--bg-3)', borderRadius: height / 2, overflow: 'hidden' }}>
      <div style={{
        height: '100%', width: (v * 100).toFixed(1) + '%', background: color,
        transition: 'width 0.4s', borderRadius: height / 2,
      }}/>
    </div>
  );
}

// ── File drop zone ──
export function FileSlot({ file, setFile, accept }) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);

  const onPick = (f) => { if (f) setFile(f); };

  if (file) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 12px',
        background: 'var(--bg-2)', border: '1px solid var(--accent-dim)',
        borderRadius: 6,
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: 5,
          background: 'var(--bg-3)', border: '1px solid var(--line)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--accent)', flexShrink: 0,
        }}>{I.check}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>
            {(file.size / (1024 * 1024)).toFixed(1)} MB
          </div>
        </div>
        <button className="btn-ghost" style={{ padding: 4, color: 'var(--ink-3)' }} onClick={() => setFile(null)}>{I.cancel}</button>
      </div>
    );
  }

  return (
    <div
      className={'dropzone' + (drag ? ' dragging' : '')}
      onClick={() => inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={e => {
        e.preventDefault(); setDrag(false);
        if (e.dataTransfer.files[0]) onPick(e.dataTransfer.files[0]);
      }}
    >
      <input ref={inputRef} type="file" accept={accept} style={{ display: 'none' }}
        onChange={e => onPick(e.target.files[0])}/>
      <div style={{
        width: 36, height: 36, margin: '0 auto 8px', borderRadius: 8,
        background: 'var(--bg-2)', border: '1px solid var(--line)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--ink-2)',
      }}>{I.upload}</div>
      <div style={{ fontSize: 13, color: 'var(--ink)', marginBottom: 3 }}>Drop or click to choose</div>
      <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>video/audio · up to 4 GB</div>
    </div>
  );
}

