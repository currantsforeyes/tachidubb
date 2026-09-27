// Voices view — reference library (upload / edit / delete)
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect } = React;
import { LANGS } from '../constants';

// ═══════════════════════════════════════════════════════════════════
// VOICES VIEW — voice reference library (upload, edit, delete clone refs)
// ═══════════════════════════════════════════════════════════════════
export function VoicesView() {
  const [presets, setPresets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState(null);  // preset being edited

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/voice_presets');
      const d = await r.json();
      setPresets(d.presets || []);
    } catch (_) {}
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const filePresets = presets.filter(p => p.type === 'file');
  const stylePresets = presets.filter(p => p.type === 'style');

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: 32, background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1080, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
          <div className="caps">Voice library</div>
          <div style={{ flex: 1 }}/>
          <button className="btn btn-primary" onClick={() => setUploadOpen(true)}>
            + Upload reference voice
          </button>
        </div>
        <div className="serif" style={{ fontSize: 32, marginBottom: 6 }}>
          Voices, <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>cloneable.</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--ink-3)', maxWidth: 640, marginBottom: 32 }}>
          Upload short reference clips (5-30 sec, clear speech, one speaker, no music) and
          reuse them across dubs. Files live in <span className="mono" style={{ color: 'var(--ink-2)' }}>presets/voices/</span> —
          re-scanned on every call, no restart needed.
        </div>

        {loading && <div className="mono" style={{ color: 'var(--ink-4)' }}>Loading…</div>}

        {/* My voices (file-based) */}
        {!loading && (
          <div style={{ marginBottom: 40 }}>
            <div className="caps" style={{ marginBottom: 12 }}>
              My voices · {filePresets.length}
            </div>
            {filePresets.length === 0 ? (
              <div style={{
                padding: 32, textAlign: 'center', borderRadius: 8,
                background: 'var(--bg-1)', border: '1px dashed var(--line)',
              }}>
                <div style={{ fontSize: 14, color: 'var(--ink-3)', marginBottom: 10 }}>
                  No custom voices yet.
                </div>
                <button className="btn" onClick={() => setUploadOpen(true)}>
                  Upload your first reference
                </button>
              </div>
            ) : (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: 14,
              }}>
                {filePresets.map(p => (
                  <VoiceCard key={p.id} preset={p}
                             onEdit={() => setEditing(p)}
                             onDeleted={load}/>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Built-in style presets — read-only */}
        {!loading && stylePresets.length > 0 && (
          <div>
            <div className="caps" style={{ marginBottom: 12 }}>
              Built-in styles · {stylePresets.length}
            </div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--ink-4)', marginBottom: 10 }}>
              No reference audio — these are voice-design prompts with a fixed seed
              for reproducibility. Cannot be edited or deleted.
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 10,
            }}>
              {stylePresets.map(p => (
                <div key={p.id} style={{
                  padding: 12, background: 'var(--bg-1)',
                  border: '1px solid var(--line)', borderRadius: 6,
                }}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
                  {p.style && (
                    <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 4 }}>
                      {p.style}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {uploadOpen && (
        <VoiceUploadModal
          onClose={() => setUploadOpen(false)}
          onUploaded={() => { setUploadOpen(false); load(); }}/>
      )}
      {editing && (
        <VoiceEditModal preset={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}/>
      )}
    </div>
  );
}

export function VoiceCard({ preset, onEdit, onDeleted }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const del = async () => {
    setBusy(true);
    try {
      const r = await fetch(`/api/voice_presets/${preset.id}`, { method: 'DELETE' });
      if (r.ok) onDeleted();
      else alert((await r.json()).error || 'Delete failed');
    } finally { setBusy(false); setConfirming(false); }
  };
  return (
    <div style={{
      padding: 14, background: 'var(--bg-1)',
      border: '1px solid var(--line)', borderRadius: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 500, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {preset.name}
        </div>
        {preset.gender && (
          <span className="mono" style={{ fontSize: 9, color: 'var(--ink-4)' }}>
            {preset.gender.charAt(0).toUpperCase()}
          </span>
        )}
        {preset.language && (
          <span className="mono" style={{
            fontSize: 9, padding: '1px 5px', borderRadius: 3,
            background: 'var(--bg-2)', color: 'var(--ink-3)',
          }}>
            {preset.language.toUpperCase()}
          </span>
        )}
      </div>
      {preset.description && (
        <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginBottom: 8, lineHeight: 1.5 }}>
          {preset.description}
        </div>
      )}
      <audio src={preset.audio_url} controls
             style={{ width: '100%', height: 32 }}/>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 8, flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 9, color: 'var(--ink-4)' }}>
          {(preset.file_size / 1024).toFixed(0)} KB · {preset.file_ext}
        </span>
        {(preset.tags || []).map(t => (
          <span key={t} className="mono" style={{
            fontSize: 9, padding: '1px 5px', borderRadius: 3,
            background: 'var(--bg-2)', color: 'var(--ink-3)',
          }}>{t}</span>
        ))}
        <div style={{ flex: 1 }}/>
        <button className="btn-ghost" onClick={onEdit}
                style={{ padding: '2px 6px', fontSize: 10 }}>
          edit
        </button>
        {confirming ? (
          <>
            <button className="btn" onClick={del} disabled={busy}
                    style={{ padding: '2px 6px', fontSize: 10, color: 'var(--err)' }}>
              {busy ? '…' : 'confirm'}
            </button>
            <button className="btn-ghost" onClick={() => setConfirming(false)}
                    style={{ padding: '2px 4px', fontSize: 10 }}>×</button>
          </>
        ) : (
          <button className="btn-ghost" onClick={() => setConfirming(true)}
                  style={{ padding: '2px 6px', fontSize: 10, color: 'var(--err)' }}>
            delete
          </button>
        )}
      </div>
    </div>
  );
}

export function VoiceUploadModal({ onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [gender, setGender] = useState('');
  const [language, setLanguage] = useState('');
  const [tags, setTags] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Auto-derive name from filename
  const onFile = (f) => {
    setFile(f);
    if (f && !name) {
      const stem = f.name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9 _\-]/g, '_');
      setName(stem.slice(0, 50));
    }
  };

  const submit = async () => {
    setError(null);
    if (!file) return setError('Choose an audio file');
    if (!name.trim()) return setError('Name is required');
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('audio', file);
      fd.append('name', name.trim());
      fd.append('description', description);
      fd.append('gender', gender);
      fd.append('language', language);
      fd.append('tags', tags);
      const r = await fetch('/api/voice_presets', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.ok) onUploaded();
      else setError(d.error || 'Upload failed');
    } catch (e) { setError(String(e.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <ModalShell title="Upload voice reference" onClose={onClose}>
      <div className="caps" style={{ marginBottom: 6 }}>Audio file</div>
      <input type="file" accept="audio/*"
             onChange={e => onFile(e.target.files?.[0] || null)}
             className="field" style={{ marginBottom: 14 }}/>

      <div className="caps" style={{ marginBottom: 6 }}>Name *</div>
      <input value={name} onChange={e => setName(e.target.value)}
             className="field" placeholder="e.g. alex_warm" maxLength={50}
             style={{ marginBottom: 14 }}/>

      <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
        <div style={{ flex: 1 }}>
          <div className="caps" style={{ marginBottom: 6 }}>Gender</div>
          <select value={gender} onChange={e => setGender(e.target.value)} className="field">
            <option value="">(unset)</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="neutral">Neutral</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <div className="caps" style={{ marginBottom: 6 }}>Language hint</div>
          <select value={language} onChange={e => setLanguage(e.target.value)} className="field">
            <option value="">(any)</option>
            {LANGS.filter(l => l.c !== 'auto').map(l => (
              <option key={l.c} value={l.c}>{l.n}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="caps" style={{ marginBottom: 6 }}>Description</div>
      <textarea value={description} onChange={e => setDescription(e.target.value)}
                className="field" rows={2}
                placeholder="e.g. warm middle-aged narrator, calm and clear"
                style={{ marginBottom: 14, resize: 'vertical' }}/>

      <div className="caps" style={{ marginBottom: 6 }}>Tags (comma-separated)</div>
      <input value={tags} onChange={e => setTags(e.target.value)}
             className="field" placeholder="narrator, calm, en-us"
             style={{ marginBottom: 18 }}/>

      {error && (
        <div className="mono" style={{ fontSize: 11, color: 'var(--err)', marginBottom: 12 }}>{error}</div>
      )}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" onClick={submit} disabled={busy || !file || !name.trim()}>
          {busy ? 'Uploading…' : 'Save voice'}
        </button>
      </div>
    </ModalShell>
  );
}

export function VoiceEditModal({ preset, onClose, onSaved }) {
  const [name, setName] = useState(preset.name || '');
  const [description, setDescription] = useState(preset.description || '');
  const [gender, setGender] = useState(preset.gender || '');
  const [language, setLanguage] = useState(preset.language || '');
  const [tags, setTags] = useState((preset.tags || []).join(', '));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setError(null); setBusy(true);
    try {
      const fd = new FormData();
      if (name.trim() && name.trim() !== preset.name) fd.append('name', name.trim());
      fd.append('description', description);
      fd.append('gender', gender);
      fd.append('language', language);
      fd.append('tags', tags);
      const r = await fetch(`/api/voice_presets/${preset.id}`, { method: 'PUT', body: fd });
      const d = await r.json();
      if (d.ok) onSaved();
      else setError(d.error || 'Save failed');
    } catch (e) { setError(String(e.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <ModalShell title={`Edit · ${preset.name}`} onClose={onClose}>
      <div className="caps" style={{ marginBottom: 6 }}>Name (rename)</div>
      <input value={name} onChange={e => setName(e.target.value)}
             className="field" maxLength={50}
             style={{ marginBottom: 14 }}/>

      <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
        <div style={{ flex: 1 }}>
          <div className="caps" style={{ marginBottom: 6 }}>Gender</div>
          <select value={gender} onChange={e => setGender(e.target.value)} className="field">
            <option value="">(unset)</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="neutral">Neutral</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <div className="caps" style={{ marginBottom: 6 }}>Language</div>
          <select value={language} onChange={e => setLanguage(e.target.value)} className="field">
            <option value="">(any)</option>
            {LANGS.filter(l => l.c !== 'auto').map(l => (
              <option key={l.c} value={l.c}>{l.n}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="caps" style={{ marginBottom: 6 }}>Description</div>
      <textarea value={description} onChange={e => setDescription(e.target.value)}
                className="field" rows={2} style={{ marginBottom: 14, resize: 'vertical' }}/>

      <div className="caps" style={{ marginBottom: 6 }}>Tags</div>
      <input value={tags} onChange={e => setTags(e.target.value)}
             className="field" style={{ marginBottom: 18 }}/>

      {error && (
        <div className="mono" style={{ fontSize: 11, color: 'var(--err)', marginBottom: 12 }}>{error}</div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" onClick={submit} disabled={busy}>
          {busy ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </ModalShell>
  );
}

export function ModalShell({ title, onClose, children }) {
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(520px, 92vw)', maxHeight: '90vh', overflow: 'auto',
        background: 'var(--bg-1)', border: '1px solid var(--line)',
        borderRadius: 10, padding: 22,
      }}>
        <div className="serif" style={{ fontSize: 20, marginBottom: 14 }}>{title}</div>
        {children}
      </div>
    </div>
  );
}


