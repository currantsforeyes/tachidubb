// Result-page panels: export presets, subs burn-in, lip-sync, regenerate
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useCallback } = React;
import { I } from '../icons';
import { Field, FileSlot, Select } from '../ui';

// ── Export for Platform ────────────────────────────────────────────
export function ExportPanel({ job }) {
  const PRESETS = [
    { id: 'youtube_1080p',     name: 'YouTube 1080p',  aspect: '16:9', detail: 'Native source aspect · safe everywhere',  hot: false },
    { id: 'youtube_4k',        name: 'YouTube 4K',     aspect: '16:9', detail: 'Up-rendered to 3840×2160',                hot: false },
    { id: 'tiktok',            name: 'TikTok',         aspect: '9:16', detail: '1080×1920 · subs burned · 30 fps',         hot: true  },
    { id: 'shorts',            name: 'Shorts',         aspect: '9:16', detail: 'YouTube vertical · 1080×1920',             hot: true  },
    { id: 'reels',             name: 'Reels',          aspect: '9:16', detail: 'Instagram vertical · 1080×1920',           hot: false },
    { id: 'instagram_square',  name: 'Instagram',      aspect: '1:1',  detail: '1080×1080 · feed posts',                   hot: false },
    { id: 'twitter',           name: 'Twitter / X',    aspect: '16:9', detail: '1280×720 · 2:20 max',                      hot: false },
  ];
  const [picked, setPicked] = useState(null);
  const [rendering, setRendering] = useState(false);
  const [doneUrl, setDoneUrl] = useState(null);
  const [error, setError] = useState(null);

  // Reset result state when the user picks a different preset
  useEffect(() => { setDoneUrl(null); setError(null); }, [picked]);

  const render = async () => {
    if (!picked) return;
    setRendering(true); setDoneUrl(null); setError(null);
    try {
      const fd = new FormData();
      fd.append('preset', picked);
      const r = await fetch(`/api/dub/${job.id}/export`, { method: 'POST', body: fd });
      const d = await r.json();
      if (d.url) setDoneUrl(d.url);
      else setError(d.error || d.detail || 'Export failed');
    } catch (e) { setError(String(e)); }
    finally { setRendering(false); }
  };

  const pickedPreset = PRESETS.find(p => p.id === picked);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <div className="serif" style={{ fontSize: 22 }}>Export for platform</div>
        <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>· pick a destination, we handle the format</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(178px, 1fr))', gap: 10 }}>
        {PRESETS.map(p => (
          <PresetCard key={p.id} p={p} active={picked === p.id} onClick={() => setPicked(picked === p.id ? null : p.id)}/>
        ))}
      </div>
      {picked && (
        <div style={{
          marginTop: 14, padding: 16,
          background: 'var(--bg-1)', border: '1px solid var(--accent-dim)',
          borderRadius: 10, animation: 'slideUp 0.2s',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 12.5, color: 'var(--ink)', fontWeight: 500 }}>
              {pickedPreset?.name} — {pickedPreset?.detail}
            </div>
            <div style={{ flex: 1 }}/>
            <button className="btn-ghost" style={{ padding: 4, color: 'var(--ink-3)' }} onClick={() => setPicked(null)}>{I.cancel}</button>
          </div>
          {error && (
            <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginBottom: 8, lineHeight: 1.5 }}>
              {I.warn} {error}
            </div>
          )}
          {doneUrl ? (
            <a href={doneUrl} download
              className="btn btn-primary"
              style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center', width: '100%' }}>
              {I.arrow} Download {pickedPreset?.name}
            </a>
          ) : (
            <button onClick={render} disabled={rendering} className="btn btn-primary"
              style={{ width: '100%', justifyContent: 'center' }}>
              {rendering ? `Rendering for ${pickedPreset?.name}…` : `Render for ${pickedPreset?.name}  ▸`}
            </button>
          )}
          {rendering && (
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 6, textAlign: 'center' }}>
              re-encoding · {pickedPreset?.detail} · may take 30–120s
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function PresetCard({ p, active, onClick }) {
  const isVert = p.aspect === '9:16';
  const isSquare = p.aspect === '1:1';
  const fW = isVert ? 28 : isSquare ? 38 : 56;
  const fH = isVert ? 50 : isSquare ? 38 : 32;
  return (
    <button onClick={onClick} style={{
      padding: 14, textAlign: 'left',
      background: active ? 'var(--bg-2)' : 'var(--bg-1)',
      border: '1px solid ' + (active ? 'var(--accent)' : 'var(--line)'),
      borderRadius: 8, cursor: 'pointer', position: 'relative',
      transition: 'all 0.12s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <div style={{
          width: fW, height: fH, background: active ? 'var(--accent)' : 'var(--bg-3)',
          borderRadius: 3, flexShrink: 0,
          border: '1px solid ' + (active ? 'var(--accent)' : 'var(--line-2)'),
        }}/>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: 6 }}>
            {p.name}
            {p.hot && <span className="mono" style={{ fontSize: 8, color: 'var(--accent)', padding: '1px 4px', border: '1px solid var(--accent)', borderRadius: 3 }}>HOT</span>}
          </div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>{p.aspect}</div>
        </div>
      </div>
      <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.4 }}>{p.detail}</div>
      {active && (
        <div style={{ position: 'absolute', top: 8, right: 8, color: 'var(--accent)' }}>{I.check}</div>
      )}
    </button>
  );
}

// ── Dialogue editor — DAW-style multi-track workspace ───────────────
// Layout follows the design mock: video + transport on top, a timecode ruler,
// and aligned lanes (Original Text / Translated Text / one waveform lane per
// speaker). Dragging the translated clips edits segment starts; "Apply timing"
// persists them through /timeline.
export function ExpandPanel({ open, onToggle, title, subtitle, icon, children }) {
  return (
    <div style={{
      background: 'var(--bg-1)', border: '1px solid ' + (open ? 'var(--line-2)' : 'var(--line)'),
      borderRadius: 8, marginBottom: 8, overflow: 'hidden',
    }}>
      <button onClick={onToggle} style={{
        width: '100%', padding: '14px 18px',
        display: 'flex', alignItems: 'center', gap: 12,
        textAlign: 'left', cursor: 'pointer',
      }}>
        <div style={{
          width: 30, height: 30, borderRadius: 6,
          background: 'var(--bg-2)', border: '1px solid var(--line)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--ink-2)', flexShrink: 0,
        }}>{icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>{title}</div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 2 }}>{subtitle}</div>
        </div>
        <div style={{
          transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
          transition: 'transform 0.15s', color: 'var(--ink-3)', fontSize: 11,
        }}>▾</div>
      </button>
      {open && (
        <div style={{ padding: '6px 18px 18px', borderTop: '1px solid var(--line)', animation: 'fadeIn 0.15s' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ── Burn subs panel ──────────────────────────────────────────────────
export function SubsPanel({ job, onBurned }) {
  const STYLES = [
    { id: 'default', name: 'Default',   detail: 'White outline, medium · safe' },
    { id: 'large',   name: 'Large',     detail: 'Bold + bigger · ideal for vertical' },
    { id: 'minimal', name: 'Minimal',   detail: 'Thin outline, smaller · clean studio' },
    { id: 'yellow',  name: 'Yellow',    detail: 'Classic cinema · sports / action' },
    { id: 'boxed',   name: 'Boxed',     detail: 'Opaque box · noisy backgrounds' },
  ];
  const [style, setStyle] = useState('default');
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [burning, setBurning] = useState(false);
  const [error, setError] = useState(null);

  // Re-fetch preview when style changes
  useEffect(() => {
    let stale = false;
    setPreviewing(true); setError(null);
    const fd = new FormData();
    fd.append('style', style);
    fd.append('timestamp', '-1');
    fetch(`/api/dub/${job.id}/subs_preview`, { method: 'POST', body: fd })
      .then(r => r.json())
      .then(d => {
        if (stale) return;
        if (d.url || d.preview_url) setPreviewUrl((d.url || d.preview_url) + '?t=' + Date.now());
        else if (d.error) setError(d.error);
      })
      .catch(e => { if (!stale) setError(String(e)); })
      .finally(() => { if (!stale) setPreviewing(false); });
    return () => { stale = true; };
  }, [style, job.id]);

  const burn = async () => {
    setBurning(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('style', style);
      const r = await fetch(`/api/dub/${job.id}/burn_subs`, { method: 'POST', body: fd });
      const d = await r.json();
      if (d.url) onBurned(d.url);
      else setError(d.error || d.detail || 'Burn failed');
    } catch (e) { setError(String(e)); }
    finally { setBurning(false); }
  };

  return (
    <div style={{ display: 'flex', gap: 14, marginTop: 14 }}>
      <div style={{ flex: 1 }}>
        <div className="caps" style={{ marginBottom: 8 }}>Style</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {STYLES.map(s => (
            <button key={s.id} onClick={() => setStyle(s.id)} style={{
              padding: '9px 12px', textAlign: 'left',
              background: style === s.id ? 'var(--bg-2)' : 'var(--bg-1)',
              border: '1px solid ' + (style === s.id ? 'var(--accent)' : 'var(--line)'),
              borderRadius: 6, color: 'var(--ink)', cursor: 'pointer',
            }}>
              <div style={{ fontSize: 12.5, fontWeight: 500 }}>{s.name}</div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2 }}>{s.detail}</div>
            </button>
          ))}
        </div>
      </div>
      <div style={{ width: 360, flexShrink: 0 }}>
        <div className="caps" style={{ marginBottom: 8 }}>Preview · single frame</div>
        <div style={{
          width: '100%', aspectRatio: '16 / 9',
          background: '#0d0f14', border: '1px solid var(--line)', borderRadius: 6,
          overflow: 'hidden', position: 'relative',
        }}>
          {previewUrl
            ? <img src={previewUrl} alt="preview" style={{ width: '100%', height: '100%', objectFit: 'contain' }}/>
            : (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8 }}>
                {previewing
                  ? <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>Rendering preview…</span>
                  : <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>—</span>}
              </div>
            )
          }
        </div>
        {error && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 6, lineHeight: 1.5 }}>
            {I.warn} {error}
          </div>
        )}
        <button onClick={burn} disabled={burning} className="btn btn-primary" style={{ marginTop: 10, width: '100%', justifyContent: 'center' }}>
          {burning ? 'Burning…' : 'Burn into full video  ▸'}
        </button>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 6, textAlign: 'center' }}>
          preview ~2s · full burn ~30-90s
        </div>
      </div>
    </div>
  );
}

// ── Lip-sync panel ──────────────────────────────────────────────────
export function LipSyncPanel({ job, onSynced }) {
  const [lipStatus, setLipStatus] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    fetch('/api/lip_sync/status').then(r => r.json()).then(setLipStatus).catch(() => {});
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const run = async () => {
    setRunning(true); setError(null);
    try {
      const r = await fetch(`/api/dub/${job.id}/lip_sync`, { method: 'POST' });
      const d = await r.json();
      if (d.url) onSynced(d.url);
      else if (d.error) setError(d.error);
      else if (d.guide) {/* not installed */}
    } catch (e) { setError(String(e)); }
    finally { setRunning(false); }
  };

  if (!lipStatus) {
    return <div style={{ paddingTop: 14, fontSize: 12, color: 'var(--ink-3)' }}>Checking…</div>;
  }

  if (!lipStatus.installed) {
    const guide = lipStatus.guide || {};
    const steps = guide.steps || [
      'install-musetalk.bat   (Windows)  /  ./install-musetalk.sh   (Linux/macOS)',
      'Restart TachiDUBB Studio',
    ];
    return (
      <div style={{ paddingTop: 14 }}>
        <div style={{
          padding: 12, marginBottom: 12,
          background: 'oklch(0.78 0.15 60 / 0.08)',
          border: '1px solid oklch(0.78 0.15 60 / 0.25)',
          borderRadius: 6, display: 'flex', gap: 10, alignItems: 'flex-start',
        }}>
          <span style={{ color: 'var(--warn)', marginTop: 2 }}>{I.warn}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, color: 'var(--ink)', fontWeight: 500, marginBottom: 4 }}>
              MuseTalk not installed
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)', lineHeight: 1.5 }}>
              Optional one-time setup. Creates an isolated runtime and downloads model weights. Only worth installing if your videos are mostly close-up talking heads.
            </div>
          </div>
        </div>
        <div className="caps" style={{ marginBottom: 8 }}>Install steps · copy & run</div>
        {steps.map((cmd, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 12px', background: 'var(--bg-2)', border: '1px solid var(--line)',
            borderRadius: 6, marginBottom: 6,
          }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', width: 20 }}>{i + 1}</span>
            <code className="mono" style={{ fontSize: 11, color: 'var(--ink-2)', flex: 1, overflow: 'auto', whiteSpace: 'nowrap' }}>{cmd}</code>
            <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(cmd)} style={{ padding: 4, color: 'var(--ink-3)' }} title="Copy">{I.copy}</button>
          </div>
        ))}
        <button onClick={refresh} className="btn" style={{ marginTop: 10 }}>
          {I.refresh} Check again
        </button>
      </div>
    );
  }

  return (
    <div style={{ paddingTop: 14 }}>
      <div style={{ fontSize: 12.5, color: 'var(--ink-2)', marginBottom: 10 }}>
        MuseTalk detected at <code className="mono" style={{ color: 'var(--ink)' }}>{lipStatus.repo_dir}</code>
      </div>
      <button onClick={run} disabled={running} className="btn btn-primary">
        {running ? 'Running lip-sync…' : 'Run lip-sync pass  ▸'}
      </button>
      {error && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 8, lineHeight: 1.5 }}>
          {I.warn} {error}
        </div>
      )}
      <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 8 }}>
        ~real-time on a modern GPU · faces must be visible &amp; centered
      </div>
    </div>
  );
}

// ── Regenerate-with-different-voice panel ──────────────────────────
export function RegenPanel({ job, voicePresets, onSubmitted }) {
  const [voicePreset, setVoicePreset] = useState(job.voice_preset || 'auto');
  const [voiceStyle, setVoiceStyle] = useState('');
  const [ttsSpeed, setTtsSpeed] = useState(job.tts_speed || 'balanced');
  const [refFile, setRefFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setSubmitting(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('voice_preset', voicePreset);
      fd.append('voice_style', voiceStyle);
      fd.append('tts_speed', ttsSpeed);
      if (refFile) fd.append('reference', refFile);
      const r = await fetch(`/api/dub/${job.id}/retry_tts`, { method: 'POST', body: fd });
      const d = await r.json();
      if (d.ok) onSubmitted();
      else setError(d.error || d.detail || 'Submit failed');
    } catch (e) { setError(String(e)); }
    finally { setSubmitting(false); }
  };

  return (
    <div style={{ paddingTop: 14, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
      <div>
        <Field label="Voice preset">
          <Select value={voicePreset} onChange={setVoicePreset}>
            <option value="auto" style={{ background: '#16161c' }}>auto · clone source</option>
            {voicePresets.map(p => (
              <option key={p.id} value={p.id} style={{ background: '#16161c' }}>{p.name}</option>
            ))}
          </Select>
        </Field>
        <div style={{ marginTop: 12 }}>
          <Field label="Voice style (optional)" hint="Free-text prompt: 'warm female narrator', 'energetic young male'.">
            <input className="field" value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)} placeholder="—"/>
          </Field>
        </div>
      </div>
      <div>
        <Field label="Voice reference (optional)" hint="WAV/MP3 of clean speech.">
          <FileSlot file={refFile} setFile={setRefFile} accept="audio/*"/>
        </Field>
        <div style={{ marginTop: 12 }}>
          <Field label="TTS speed">
            <div style={{ display: 'flex', gap: 6 }}>
              {['fast', 'balanced', 'quality'].map(s => (
                <button key={s} onClick={() => setTtsSpeed(s)} className="btn" style={{
                  flex: 1, justifyContent: 'center',
                  borderColor: ttsSpeed === s ? 'var(--accent)' : 'var(--line)',
                  background: ttsSpeed === s ? 'var(--bg-2)' : 'var(--bg-1)',
                  color: ttsSpeed === s ? 'var(--ink)' : 'var(--ink-2)',
                }}>{s}</button>
              ))}
            </div>
          </Field>
        </div>
        <button onClick={submit} disabled={submitting} className="btn btn-primary" style={{ marginTop: 14, width: '100%', justifyContent: 'center' }}>
          {submitting ? 'Queueing…' : 'Regenerate all segments  ▸'}
        </button>
        {error && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 8 }}>
            {I.warn} {error}
          </div>
        )}
      </div>
    </div>
  );
}

