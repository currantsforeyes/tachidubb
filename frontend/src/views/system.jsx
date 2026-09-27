// System view — overview / models / storage / glossary / add-ons
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useCallback, useMemo } = React;
import { I } from '../icons';
import { LongProgress } from '../ui';

// ═══════════════════════════════════════════════════════════════════
// SYSTEM VIEW — 5 tabs: Overview / Models / Storage / Glossary / Add-ons
// ═══════════════════════════════════════════════════════════════════
export function SystemView({ system, onRefreshSystem }) {
  const [tab, setTab] = useState('overview');
  return (
    <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '36px 36px 80px' }}>

        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 22, gap: 20 }}>
          <div>
            <div className="caps">System</div>
            <div className="serif" style={{ fontSize: 36, lineHeight: 1.05, letterSpacing: '-0.015em', marginTop: 4 }}>
              What's running, <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>and what isn't</span>.
            </div>
            <div style={{ color: 'var(--ink-3)', marginTop: 6, fontSize: 13, maxWidth: 540 }}>
              GPU status, models, storage, and a JSON-level glossary editor. Everything lives on your machine.
            </div>
          </div>
          <button onClick={onRefreshSystem} className="btn">{I.refresh} Refresh</button>
        </div>

        <div style={{ display: 'flex', gap: 22, borderBottom: '1px solid var(--line)', marginBottom: 24 }}>
          {[
            ['overview', 'Overview'],
            ['models',   'Models'],
            ['storage',  'Storage'],
            ['glossary', 'Glossary'],
            ['pronunciation', 'Pronunciation'],
            ['addons',   'Add-ons'],
          ].map(([id, label]) => (
            <div key={id} className={'tab' + (tab === id ? ' active' : '')} onClick={() => setTab(id)}>
              {label}
            </div>
          ))}
        </div>

        {tab === 'overview' && <SysOverview system={system}/>}
        {tab === 'models'   && <SysModels system={system} onRefresh={onRefreshSystem}/>}
        {tab === 'storage'  && <SysStorage/>}
        {tab === 'glossary' && <SysGlossary/>}
        {tab === 'pronunciation' && <SysPronunciation/>}
        {tab === 'addons'   && <SysAddons/>}
      </div>
    </div>
  );
}

export function SysOverview({ system }) {
  if (!system) {
    return <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>Loading…</div>;
  }
  const gpu = system.gpu || {};
  const vramTotal = gpu.vram_gb;
  const vramFree = gpu.vram_free_gb;
  const vramUsed = (vramTotal != null && vramFree != null) ? Math.max(0, vramTotal - vramFree) : null;
  const vramPct = (vramTotal && vramUsed != null) ? vramUsed / vramTotal : 0;

  const subsystems = [
    ['Python',    system.python,    'runtime'],
    ['ffmpeg',    system.ffmpeg,    'video / audio'],
    ['yt-dlp',    system.yt_dlp,    'URL ingestion'],
    ['Whisper',   system.whisper,   'transcription'],
    ['VoxCPM',    system.voxcpm,    'TTS · primary'],
    ['Edge TTS',  system.edge_tts,  'TTS · fallback'],
    ['pyannote',  system.pyannote,  'diarization'],
    ['Ollama',    system.ollama,    'translation'],
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14 }}>
      {/* GPU */}
      <div style={{ padding: 18, background: 'var(--bg-1)', border: '1px solid ' + (gpu.ok ? 'var(--line)' : 'oklch(0.7 0.2 25 / 0.3)'), borderRadius: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ color: 'var(--ink-3)' }}>{I.cpu}</span>
          <div className="caps">GPU</div>
          <div style={{ flex: 1 }}/>
          <span className="chip" style={{
            color: gpu.ok ? 'var(--accent)' : 'var(--err)',
            borderColor: gpu.ok ? 'var(--accent-dim)' : 'oklch(0.7 0.2 25 / 0.3)',
            background: gpu.ok ? 'var(--accent-dim)' : 'oklch(0.7 0.2 25 / 0.1)',
          }}>
            <span className="dot" style={{ background: gpu.ok ? 'var(--accent)' : 'var(--err)' }}/>
            {gpu.ok ? 'CUDA OK' : 'No CUDA'}
          </span>
        </div>
        <div className="serif" style={{ fontSize: 20, color: 'var(--ink)', marginBottom: 6 }}>
          {gpu.name || '—'}
        </div>
        {gpu.ok ? (
          <>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 8 }}>
              <span className="serif" style={{ fontSize: 24 }}>{vramUsed?.toFixed(1) ?? '—'}</span>
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>/ {vramTotal} GB · VRAM used</span>
            </div>
            <div style={{ marginTop: 8 }}>
              <LongProgress value={vramPct} color="var(--accent)" height={4}/>
              <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 5 }}>
                {(vramPct * 100).toFixed(0)}% in use · {vramFree?.toFixed(1)} GB free
              </div>
            </div>
          </>
        ) : (
          <div style={{ marginTop: 10, padding: 10, background: 'oklch(0.7 0.2 25 / 0.06)', border: '1px solid oklch(0.7 0.2 25 / 0.2)', borderRadius: 6, fontSize: 11.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
            torch.cuda not available. Reinstall torch with the matching CUDA wheel:
            <pre className="mono" style={{ fontSize: 10, color: 'var(--ink)', marginTop: 6, padding: 6, background: 'var(--bg)', borderRadius: 4, overflow: 'auto' }}>
{`pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio \\
  --index-url https://download.pytorch.org/whl/cu121`}
            </pre>
          </div>
        )}
      </div>

      {/* Pipeline ready */}
      <div style={{ padding: 18, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <div className="caps">Pipeline status</div>
          <div style={{ flex: 1 }}/>
          <span className="chip" style={{
            color: system.ready ? 'var(--accent)' : 'var(--warn)',
            borderColor: system.ready ? 'var(--accent-dim)' : 'oklch(0.78 0.15 60 / 0.3)',
            background: system.ready ? 'var(--accent-dim)' : 'oklch(0.78 0.15 60 / 0.1)',
          }}>
            <span className="dot" style={{ background: system.ready ? 'var(--accent)' : 'var(--warn)' }}/>
            {system.ready ? 'Ready' : 'Setup needed'}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {subsystems.map(([name, info, hint]) => {
            const ok = info?.ok;
            return (
              <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <span style={{ color: ok ? 'var(--accent)' : 'var(--ink-4)' }}>
                  {ok ? I.check : I.cancel}
                </span>
                <span style={{ color: ok ? 'var(--ink-2)' : 'var(--ink-3)', fontWeight: 500 }}>{name}</span>
                <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginLeft: 'auto' }}>{hint}</span>
                {info?.version && <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>v{info.version}</span>}
              </div>
            );
          })}
        </div>
      </div>

      {/* Models summary */}
      <div style={{ padding: 18, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
        <div className="caps" style={{ marginBottom: 10 }}>Installed translation models</div>
        <div style={{ fontSize: 13, color: 'var(--ink-2)' }}>
          <span className="serif" style={{ fontSize: 26, color: 'var(--ink)' }}>
            {(system.ollama?.models?.length) || 0}
          </span>
          <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginLeft: 6 }}>via Ollama</span>
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--ink-3)' }}>
          {(system.ollama?.models || []).slice(0, 4).map(m => (
            <div key={m.name || m} className="mono" style={{ marginBottom: 3 }}>· {m.name || m}</div>
          ))}
          {(system.ollama?.models?.length || 0) > 4 && (
            <div className="mono" style={{ color: 'var(--ink-4)' }}>+ {system.ollama.models.length - 4} more</div>
          )}
        </div>
      </div>

      {/* Workspace */}
      <div style={{ padding: 18, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
        <div className="caps" style={{ marginBottom: 10 }}>Workspace</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 11.5, color: 'var(--ink-3)' }}>
          <div><span className="mono" style={{ color: 'var(--ink-2)' }}>~/tachidubb/output/</span> · job working directories</div>
          <div><span className="mono" style={{ color: 'var(--ink-2)' }}>~/tachidubb/uploads/</span> · uploaded source files</div>
          <div><span className="mono" style={{ color: 'var(--ink-2)' }}>presets/voices/</span> · custom voice references</div>
          <div><span className="mono" style={{ color: 'var(--ink-2)' }}>presets/user_glossary.json</span> · translation overrides</div>
        </div>
      </div>
    </div>
  );
}

// ── Models tab ──────────────────────────────────────────────────────
export function SysModels({ system, onRefresh }) {
  const installed = useMemo(() => {
    const arr = system?.ollama?.models || [];
    return new Set(arr.map(m => (typeof m === 'string' ? m : m.name)).filter(Boolean));
  }, [system]);
  const catalog = system?.catalog?.translation || [];

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <div className="serif" style={{ fontSize: 22 }}>Translation models · Ollama</div>
        <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>· installed locally · pull/delete via Ollama HTTP API</span>
      </div>
      <div style={{ border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden', background: 'var(--bg-1)' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 0.6fr 0.6fr 2fr 130px',
          padding: '10px 16px', gap: 12, background: 'var(--bg-2)',
          borderBottom: '1px solid var(--line)',
        }}>
          {['Model', 'Size', 'VRAM', 'About', ''].map((h, i) => <div key={i} className="caps">{h}</div>)}
        </div>
        {catalog.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-3)', fontSize: 12 }}>
            Catalog not loaded — refresh.
          </div>
        )}
        {catalog.map((m, i) => (
          <ModelRow key={m.id} model={m} installed={installed.has(m.id)} last={i === catalog.length - 1} onChanged={onRefresh}/>
        ))}
      </div>
    </div>
  );
}

export function ModelRow({ model, installed, last, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null);

  const pull = async () => {
    setBusy(true); setProgress(0);
    const fd = new FormData();
    fd.append('model', model.id);
    try {
      const r = await fetch('/api/models/pull', { method: 'POST', body: fd });
      // SSE stream
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.percent != null) setProgress(ev.percent);
            if (ev.status === 'success') setProgress(100);
            if (ev.status === 'error') alert('Pull failed: ' + (ev.error || '?'));
          } catch (_) {}
        }
      }
      onChanged();
    } catch (e) {
      alert('Pull failed: ' + e);
    } finally {
      setBusy(false); setProgress(null);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete ${model.id}? Frees ${model.size}.`)) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('model', model.id);
      const r = await fetch('/api/models/delete', { method: 'POST', body: fd });
      if (r.ok) onChanged();
      else alert('Delete failed');
    } finally { setBusy(false); }
  };

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 0.6fr 0.6fr 2fr 130px',
      padding: '12px 16px', gap: 12, alignItems: 'center',
      borderBottom: last ? 'none' : '1px solid var(--line)',
    }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: installed ? 'var(--ink)' : 'var(--ink-2)' }}>
          {model.name}
          {model.recommended && <span className="mono" style={{ fontSize: 9, color: 'var(--accent)', marginLeft: 6, padding: '1px 5px', border: '1px solid var(--accent)', borderRadius: 3 }}>RECOMMENDED</span>}
        </div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>{model.id}</div>
      </div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{model.size}</div>
      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{model.vram}</div>
      <div style={{ fontSize: 11.5, color: 'var(--ink-3)', lineHeight: 1.4 }}>{model.description}</div>
      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
        {progress != null ? (
          <div style={{ width: '100%' }}>
            <LongProgress value={progress / 100} color="var(--accent)" height={3}/>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 3, textAlign: 'right' }}>
              {progress.toFixed(0)}%
            </div>
          </div>
        ) : installed ? (
          <>
            <span className="chip accent">Installed</span>
            <button onClick={remove} disabled={busy} className="btn-ghost" style={{ padding: 4, color: 'var(--err)' }} title="Delete">
              {I.trash}
            </button>
          </>
        ) : (
          <button onClick={pull} disabled={busy} className="btn btn-primary" style={{ padding: '4px 10px', fontSize: 11 }}>
            {busy ? 'Pulling…' : 'Pull'}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Storage tab ─────────────────────────────────────────────────────
export function SysStorage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  // Cleanup form
  const [olderThan, setOlderThan] = useState(7);
  const [mode, setMode] = useState('intermediate');
  const [includeErrored, setIncludeErrored] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [previewResult, setPreviewResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    fetch('/api/storage/stats').then(r => r.json()).then(d => { setStats(d); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const preview = async () => {
    setPreviewing(true);
    try {
      const fd = new FormData();
      fd.append('older_than_days', String(olderThan));
      fd.append('mode', mode);
      fd.append('dry_run', 'true');
      fd.append('include_errored', String(includeErrored));
      fd.append('include_cancelled', 'true');
      const r = await fetch('/api/storage/cleanup', { method: 'POST', body: fd });
      const d = await r.json();
      setPreviewResult(d);
    } finally { setPreviewing(false); }
  };

  const execute = async () => {
    if (!previewResult) return;
    if (!confirm(`Delete ${previewResult.affected_count || 0} job(s) freeing ${previewResult.freed_mb?.toFixed(1) || '?'} MB?`)) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('older_than_days', String(olderThan));
      fd.append('mode', mode);
      fd.append('dry_run', 'false');
      fd.append('include_errored', String(includeErrored));
      fd.append('include_cancelled', 'true');
      await fetch('/api/storage/cleanup', { method: 'POST', body: fd });
      setPreviewResult(null);
      refresh();
    } finally { setBusy(false); }
  };

  if (loading) return <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>Loading storage stats…</div>;
  if (!stats) return <div style={{ fontSize: 12, color: 'var(--err)' }}>Could not load storage stats.</div>;

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 14, marginBottom: 24 }}>
        <div style={{ padding: 18, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
          <div className="caps" style={{ marginBottom: 10 }}>Total usage</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="serif" style={{ fontSize: 38, color: 'var(--ink)' }}>{stats.total_gb}</span>
            <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>GB across {stats.job_count} job{stats.job_count === 1 ? '' : 's'}</span>
          </div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 8 }}>
            ~/tachidubb/output/
          </div>
        </div>
        <div style={{ padding: 18, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 10 }}>
          <div className="caps" style={{ marginBottom: 10 }}>Cleanup rules</div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 5 }}>Delete files older than</div>
            <div style={{ display: 'flex', gap: 4 }}>
              {[1, 7, 30, 90].map(d => (
                <button key={d} onClick={() => { setOlderThan(d); setPreviewResult(null); }} className="btn" style={{
                  flex: 1, padding: '5px 8px', fontSize: 11,
                  borderColor: olderThan === d ? 'var(--accent)' : 'var(--line)',
                  background: olderThan === d ? 'var(--bg-2)' : 'var(--bg-1)',
                  color: olderThan === d ? 'var(--ink)' : 'var(--ink-3)',
                }}>{d}d</button>
              ))}
            </div>
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 5 }}>Mode</div>
            {[
              ['intermediate', 'Intermediate only', 'Keep mp4 + srt + checkpoints'],
              ['all_files',    'All files',         'Delete entire job dir (job record stays)'],
            ].map(([id, label, hint]) => (
              <button key={id} onClick={() => { setMode(id); setPreviewResult(null); }} style={{
                width: '100%', padding: '7px 10px', textAlign: 'left',
                background: mode === id ? 'var(--bg-2)' : 'var(--bg-1)',
                border: '1px solid ' + (mode === id ? 'var(--accent)' : 'var(--line)'),
                borderRadius: 5, color: 'var(--ink)', cursor: 'pointer',
                marginBottom: 4,
              }}>
                <div style={{ fontSize: 11.5, fontWeight: 500 }}>{label}</div>
                <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 1 }}>{hint}</div>
              </button>
            ))}
          </div>
          <button onClick={preview} disabled={previewing} className="btn" style={{ width: '100%', justifyContent: 'center' }}>
            {I.eye} {previewing ? 'Computing…' : 'Preview cleanup'}
          </button>
          {previewResult && (
            <div style={{ marginTop: 10, padding: 10, background: 'var(--bg-2)', border: '1px solid var(--line-2)', borderRadius: 6 }}>
              <div style={{ fontSize: 11.5, color: 'var(--ink-2)', marginBottom: 6 }}>
                Would delete <span className="mono" style={{ color: 'var(--ink)' }}>{previewResult.affected_count || 0}</span> job(s),
                free <span className="mono" style={{ color: 'var(--accent)' }}>{previewResult.freed_mb?.toFixed(1) || '?'} MB</span>
              </div>
              <button onClick={execute} disabled={busy} className="btn" style={{ width: '100%', justifyContent: 'center', color: 'var(--err)', borderColor: 'oklch(0.7 0.2 25 / 0.4)' }}>
                {I.trash} {busy ? 'Deleting…' : 'Execute cleanup'}
              </button>
            </div>
          )}
        </div>
      </div>

      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div className="serif" style={{ fontSize: 18 }}>Biggest jobs</div>
          <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>· starred jobs are protected from cleanup</span>
        </div>
        <div style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg-1)' }}>
          {(stats.jobs || []).slice(0, 15).map((j, i, arr) => (
            <div key={j.id} style={{
              display: 'grid', gridTemplateColumns: '30px 2fr 100px 80px 60px',
              padding: '10px 14px', alignItems: 'center', gap: 12,
              borderBottom: i === arr.length - 1 ? 'none' : '1px solid var(--line)',
            }}>
              <span style={{ color: j.starred ? '#e6c454' : 'var(--ink-4)' }}>
                {j.starred ? I.star : I.starOff}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {j.label}
                </div>
                <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>
                  {j.id?.slice(0, 8)} · {j.status}
                </div>
              </div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>{j.size_mb} MB</div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{j.age_days}d ago</div>
              <div style={{ fontSize: 10, color: 'var(--ink-4)' }}>{j.target_lang}</div>
            </div>
          ))}
          {(!stats.jobs || stats.jobs.length === 0) && (
            <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--ink-4)', fontSize: 12 }}>
              No jobs on disk yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Glossary tab — JSON editor ──────────────────────────────────────
export function SysGlossary() {
  const [text, setText] = useState('');
  const [original, setOriginal] = useState('');
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    fetch('/api/glossary').then(r => r.json()).then(d => {
      const t = JSON.stringify(d.data || { domains: [] }, null, 2);
      setText(t); setOriginal(t); setMeta(d);
    });
  }, []);
  useEffect(() => { load(); }, [load]);

  // Live JSON validity check
  const valid = useMemo(() => {
    try { JSON.parse(text); return true; } catch { return false; }
  }, [text]);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('body', text);
      const r = await fetch('/api/glossary', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.ok) {
        setOriginal(text);
        setMeta(prev => ({ ...prev, exists: true }));
      } else {
        setError(d.error || 'Save failed');
      }
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  };

  const revert = () => { setText(original); setError(null); };

  const removeFile = async () => {
    if (!confirm('Delete user_glossary.json? Built-in glossary remains.')) return;
    await fetch('/api/glossary', { method: 'DELETE' });
    load();
  };

  // Compute stats from current valid text
  const stats = useMemo(() => {
    try {
      const d = JSON.parse(text);
      const domains = d.domains || [];
      const total = domains.reduce((s, dom) => s + Object.keys(dom.terms || {}).length, 0);
      return { domainCount: domains.length, termCount: total };
    } catch { return { domainCount: 0, termCount: 0 }; }
  }, [text]);

  const dirty = text !== original;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <div className="serif" style={{ fontSize: 22 }}>User glossary</div>
        <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>· JSON overrides · merged over built-in BJJ terms</span>
        <div style={{ flex: 1 }}/>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
          {stats.termCount} terms · {stats.domainCount} domain{stats.domainCount === 1 ? '' : 's'}
        </span>
      </div>

      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{
          padding: '8px 12px', background: 'var(--bg-2)',
          borderBottom: '1px solid var(--line)',
          display: 'flex', alignItems: 'center', gap: 8, fontSize: 11,
        }}>
          <span className="mono" style={{ color: 'var(--ink-3)' }}>
            presets/user_glossary.json {meta?.exists ? '' : '(will be created on save)'}
          </span>
          <div style={{ flex: 1 }}/>
          <span className="chip" style={{
            color: valid ? 'var(--accent)' : 'var(--err)',
            borderColor: valid ? 'var(--accent-dim)' : 'oklch(0.7 0.2 25 / 0.3)',
            background: valid ? 'var(--accent-dim)' : 'oklch(0.7 0.2 25 / 0.08)',
          }}>
            <span className="dot" style={{ background: valid ? 'var(--accent)' : 'var(--err)' }}/>
            {valid ? 'Valid JSON' : 'Invalid JSON'}
          </span>
        </div>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          spellCheck={false}
          style={{
            width: '100%', minHeight: 360,
            padding: 14, background: 'var(--bg-1)', border: 'none',
            fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.6,
            color: valid ? 'var(--ink)' : 'var(--err)',
            resize: 'vertical', outline: 'none',
          }}
        />
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <button onClick={save} disabled={!valid || !dirty || saving} className="btn btn-primary">
          {I.check} {saving ? 'Saving…' : 'Save glossary'}
        </button>
        <button onClick={revert} disabled={!dirty} className="btn">{I.refresh} Revert</button>
        <div style={{ flex: 1 }}/>
        {meta?.exists && (
          <button onClick={removeFile} className="btn" style={{ color: 'var(--err)', borderColor: 'oklch(0.7 0.2 25 / 0.4)' }}>
            {I.trash} Delete user file
          </button>
        )}
      </div>

      {error && (
        <div style={{ marginTop: 10, padding: 10, background: 'oklch(0.7 0.2 25 / 0.08)', border: '1px solid oklch(0.7 0.2 25 / 0.3)', borderRadius: 6, fontSize: 11.5, color: 'var(--ink-2)' }}>
          {I.warn} {error}
        </div>
      )}

      <div style={{ marginTop: 24, padding: 14, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 8 }}>
        <div className="caps" style={{ marginBottom: 8 }}>Format</div>
        <div style={{ fontSize: 11.5, color: 'var(--ink-3)', lineHeight: 1.6 }}>
          Top-level <code className="mono" style={{ color: 'var(--ink-2)' }}>domains</code> array. Each domain has{' '}
          <code className="mono" style={{ color: 'var(--ink-2)' }}>name</code>,{' '}
          <code className="mono" style={{ color: 'var(--ink-2)' }}>triggers</code> (array of keywords matched against your{' '}
          <code className="mono" style={{ color: 'var(--ink-2)' }}>context_hint</code>),{' '}
          <code className="mono" style={{ color: 'var(--ink-2)' }}>target_lang</code>, and{' '}
          <code className="mono" style={{ color: 'var(--ink-2)' }}>terms</code> mapping source → target translations.
        </div>
      </div>
    </div>
  );
}

// ── Pronunciation tab — TTS word overrides ──────────────────────────
export function SysPronunciation() {
  const [text, setText] = useState('');
  const [original, setOriginal] = useState('');
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    fetch('/api/pronunciation').then(r => r.json()).then(d => {
      const t = JSON.stringify(d.data || { rules: [] }, null, 2);
      setText(t); setOriginal(t); setMeta(d);
    });
  }, []);
  useEffect(() => { load(); }, [load]);

  const valid = useMemo(() => {
    try { JSON.parse(text); return true; } catch { return false; }
  }, [text]);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('body', text);
      const r = await fetch('/api/pronunciation', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.ok) { setOriginal(text); setMeta(prev => ({ ...prev, exists: true })); }
      else { setError(d.error || 'Save failed'); }
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  };

  const revert = () => { setText(original); setError(null); };

  const removeFile = async () => {
    if (!confirm('Delete presets/pronunciation.json?')) return;
    await fetch('/api/pronunciation', { method: 'DELETE' });
    load();
  };

  const count = useMemo(() => {
    try { return (JSON.parse(text).rules || []).length; } catch { return 0; }
  }, [text]);

  const dirty = text !== original;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <div className="serif" style={{ fontSize: 22 }}>Pronunciation</div>
        <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>· how TTS says a word · subtitles unchanged</span>
        <div style={{ flex: 1 }}/>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
          {count} rule{count === 1 ? '' : 's'}
        </span>
      </div>

      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{
          padding: '8px 12px', background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
          display: 'flex', alignItems: 'center', gap: 8, fontSize: 11,
        }}>
          <span className="mono" style={{ color: 'var(--ink-3)' }}>
            presets/pronunciation.json {meta?.exists ? '' : '(will be created on save)'}
          </span>
          <div style={{ flex: 1 }}/>
          <span className="chip" style={{
            color: valid ? 'var(--accent)' : 'var(--err)',
            borderColor: valid ? 'var(--accent-dim)' : 'oklch(0.7 0.2 25 / 0.3)',
            background: valid ? 'var(--accent-dim)' : 'oklch(0.7 0.2 25 / 0.08)',
          }}>
            <span className="dot" style={{ background: valid ? 'var(--accent)' : 'var(--err)' }}/>
            {valid ? 'Valid JSON' : 'Invalid JSON'}
          </span>
        </div>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          spellCheck={false}
          style={{
            width: '100%', minHeight: 280, padding: 14, background: 'var(--bg-1)', border: 'none',
            fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.6,
            color: valid ? 'var(--ink)' : 'var(--err)', resize: 'vertical', outline: 'none',
          }}
        />
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <button onClick={save} disabled={!valid || !dirty || saving} className="btn btn-primary">
          {I.check} {saving ? 'Saving…' : 'Save rules'}
        </button>
        <button onClick={revert} disabled={!dirty} className="btn">{I.refresh} Revert</button>
        <div style={{ flex: 1 }}/>
        {meta?.exists && (
          <button onClick={removeFile} className="btn" style={{ color: 'var(--err)', borderColor: 'oklch(0.7 0.2 25 / 0.4)' }}>
            {I.trash} Delete file
          </button>
        )}
      </div>

      {error && (
        <div style={{ marginTop: 10, padding: 10, background: 'oklch(0.7 0.2 25 / 0.08)', border: '1px solid oklch(0.7 0.2 25 / 0.3)', borderRadius: 6, fontSize: 11.5, color: 'var(--ink-2)' }}>
          {I.warn} {error}
        </div>
      )}

      <div style={{ marginTop: 24, padding: 14, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 8 }}>
        <div className="caps" style={{ marginBottom: 8 }}>Format</div>
        <div style={{ fontSize: 11.5, color: 'var(--ink-3)', lineHeight: 1.6 }}>
          Top-level <code className="mono" style={{ color: 'var(--ink-2)' }}>rules</code> array of{' '}
          <code className="mono" style={{ color: 'var(--ink-2)' }}>{'{ "from", "to" }'}</code>. Matching is
          case-insensitive on word boundaries, and the longest <code className="mono" style={{ color: 'var(--ink-2)' }}>from</code> wins.
          Example: <code className="mono" style={{ color: 'var(--ink-2)' }}>{'{ "from": "nginx", "to": "engine x" }'}</code>
        </div>
      </div>
    </div>
  );
}

// ── Add-ons tab ─────────────────────────────────────────────────────
export function SysAddons() {
  const [lipStatus, setLipStatus] = useState(null);

  useEffect(() => {
    fetch('/api/lip_sync/status').then(r => r.json()).then(setLipStatus).catch(() => {});
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <AddonCard
        name="MuseTalk"
        detail="Match speaker mouth movement to dubbed audio. Optional. Only helps when faces are visible and centered."
        installed={lipStatus?.installed ?? null}
        size="~a few GB · one-time download"
        steps={[
          'install-musetalk.bat   (Windows)  /  ./install-musetalk.sh   (Linux/macOS)',
          'Restart TachiDUBB Studio',
        ]}
        onRefresh={() => fetch('/api/lip_sync/status').then(r => r.json()).then(setLipStatus)}
        repoDir={lipStatus?.repo_dir}
      />
      <AddonCard
        name="audio-separator"
        detail="Preserves original music and SFX during dubbing. Without this, enabling 'Keep background audio' on the Home form silently fails."
        installed={null}
        size="~800 MB with UVR model"
        steps={['pip install audio-separator']}
      />
    </div>
  );
}

export function AddonCard({ name, detail, installed, size, steps, onRefresh, repoDir }) {
  const known = installed != null;
  return (
    <div style={{
      padding: 18, background: 'var(--bg-1)',
      border: '1px solid ' + (installed ? 'var(--line)' : known ? 'oklch(0.78 0.15 60 / 0.2)' : 'var(--line)'),
      borderRadius: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div className="serif" style={{ fontSize: 20 }}>{name}</div>
            {installed === true && <span className="chip accent">Installed</span>}
            {installed === false && (
              <span className="chip" style={{ color: 'var(--warn)', borderColor: 'oklch(0.78 0.15 60 / 0.3)', background: 'oklch(0.78 0.15 60 / 0.08)' }}>
                Not installed
              </span>
            )}
            {installed == null && <span className="chip" style={{ color: 'var(--ink-3)' }}>Status unknown</span>}
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)', lineHeight: 1.5, maxWidth: 640 }}>{detail}</div>
          {repoDir && (
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 6 }}>
              Detected at: {repoDir}
            </div>
          )}
        </div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', flexShrink: 0 }}>{size}</div>
      </div>

      {installed !== true && (
        <div style={{ marginTop: 10 }}>
          <div className="caps" style={{ marginBottom: 6 }}>Install</div>
          {steps.map((cmd, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '7px 10px', background: 'var(--bg-2)', border: '1px solid var(--line)',
              borderRadius: 5, marginBottom: 4,
            }}>
              <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', width: 18 }}>{i + 1}</span>
              <code className="mono" style={{ fontSize: 11, color: 'var(--ink-2)', flex: 1, overflow: 'auto', whiteSpace: 'nowrap' }}>{cmd}</code>
              <button onClick={() => navigator.clipboard?.writeText(cmd)} className="btn-ghost" style={{ padding: 3, color: 'var(--ink-3)' }} title="Copy">{I.copy}</button>
            </div>
          ))}
          {onRefresh && (
            <button onClick={onRefresh} className="btn" style={{ marginTop: 8 }}>
              {I.refresh} Check again
            </button>
          )}
        </div>
      )}
    </div>
  );
}

