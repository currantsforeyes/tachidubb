// Glossary editor — structured translation overrides
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect } = React;
import { LANGS } from '../constants';
import { I } from '../icons';

// ═══════════════════════════════════════════════════════════════════
// GLOSSARY EDITOR — structured editor for translation overrides
// Replaces the JSON textarea with collapsible domain cards + a
// row-per-term table.
// ═══════════════════════════════════════════════════════════════════
export function GlossaryEditor() {
  const [data, setData] = useState({ domains: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/glossary');
      const d = await r.json();
      setExists(!!d.exists);
      setData(d.data || { domains: [] });
    } catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('body', JSON.stringify(data));
      const r = await fetch('/api/glossary', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.ok) { setExists(true); setSavedAt(Date.now()); }
      else setError(d.error || 'Save failed');
    } catch (e) { setError(String(e.message || e)); }
    setSaving(false);
  };

  const del = async () => {
    if (!confirm('Delete user_glossary.json? Built-in glossary stays active.')) return;
    await fetch('/api/glossary', { method: 'DELETE' });
    load();
  };

  const addDomain = () => {
    setData({
      ...data,
      domains: [...(data.domains || []), {
        name: 'New domain',
        triggers: [],
        target_lang: '',
        terms: {},
      }],
    });
  };

  const updateDomain = (i, patch) => {
    const next = [...data.domains];
    next[i] = { ...next[i], ...patch };
    setData({ ...data, domains: next });
  };

  const removeDomain = (i) => {
    if (!confirm(`Remove domain "${data.domains[i].name}"?`)) return;
    setData({ ...data, domains: data.domains.filter((_, idx) => idx !== i) });
  };

  const totalTerms = (data.domains || []).reduce(
    (a, d) => a + Object.keys(d.terms || {}).length, 0);

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: 32, background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1080, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
          <div className="caps">Translation overrides</div>
          <div style={{ flex: 1 }}/>
          {exists && (
            <button className="btn-ghost" onClick={del}
                    style={{ fontSize: 11, color: 'var(--err)' }}>
              Delete user glossary
            </button>
          )}
        </div>
        <div className="serif" style={{ fontSize: 32, marginBottom: 6 }}>
          Glossary, <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>your terms.</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--ink-3)', maxWidth: 700, marginBottom: 32 }}>
          Force specific translations for technical terms, brand names, jargon.
          Each <em>domain</em> activates only when the source contains one of its trigger words.
          Built-in BJJ glossary stays active alongside whatever you add here.
        </div>

        {loading ? (
          <div className="mono" style={{ color: 'var(--ink-4)' }}>Loading…</div>
        ) : (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 24 }}>
              {(data.domains || []).map((d, i) => (
                <GlossaryDomainCard key={i} domain={d}
                  onChange={p => updateDomain(i, p)}
                  onRemove={() => removeDomain(i)}/>
              ))}
              {(!data.domains || data.domains.length === 0) && (
                <div style={{
                  padding: 32, textAlign: 'center',
                  background: 'var(--bg-1)', border: '1px dashed var(--line)', borderRadius: 8,
                }}>
                  <div style={{ color: 'var(--ink-3)', marginBottom: 10 }}>
                    No custom domains yet.
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <button className="btn" onClick={addDomain}>+ Add domain</button>
              <div style={{ flex: 1 }}/>
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }}>
                {data.domains?.length || 0} domain(s) · {totalTerms} term(s)
              </span>
              <button className="btn btn-primary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save glossary'}
              </button>
            </div>

            {error && (
              <div className="mono" style={{ fontSize: 11, color: 'var(--err)' }}>{error}</div>
            )}
            {savedAt && !error && (
              <div className="mono" style={{ fontSize: 11, color: 'var(--accent)' }}>
                Saved · {new Date(savedAt).toLocaleTimeString()}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function GlossaryDomainCard({ domain, onChange, onRemove }) {
  const [expanded, setExpanded] = useState(true);
  const [newSrc, setNewSrc] = useState('');
  const [newDst, setNewDst] = useState('');
  const [newTrigger, setNewTrigger] = useState('');

  const terms = domain.terms || {};
  const triggers = domain.triggers || [];

  const addTerm = () => {
    const src = newSrc.trim(), dst = newDst.trim();
    if (!src || !dst) return;
    onChange({ terms: { ...terms, [src]: dst } });
    setNewSrc(''); setNewDst('');
  };
  const removeTerm = (k) => {
    const next = { ...terms };
    delete next[k];
    onChange({ terms: next });
  };
  const updateTerm = (oldKey, newKey, newVal) => {
    const next = {};
    Object.entries(terms).forEach(([k, v]) => {
      if (k === oldKey) next[newKey] = newVal;
      else next[k] = v;
    });
    onChange({ terms: next });
  };
  const addTrigger = () => {
    const t = newTrigger.trim().toLowerCase();
    if (t && !triggers.includes(t)) onChange({ triggers: [...triggers, t] });
    setNewTrigger('');
  };
  const removeTrigger = (t) => {
    onChange({ triggers: triggers.filter(x => x !== t) });
  };

  return (
    <div style={{
      background: 'var(--bg-1)', border: '1px solid var(--line)',
      borderRadius: 8, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px',
                    borderBottom: expanded ? '1px solid var(--line)' : 'none' }}>
        <button className="btn-ghost" onClick={() => setExpanded(e => !e)}
                style={{ padding: 4, color: 'var(--ink-3)' }}>
          {expanded ? '▾' : '▸'}
        </button>
        <input value={domain.name || ''}
               onChange={e => onChange({ name: e.target.value })}
               className="field"
               style={{ flex: 1, fontSize: 15, fontWeight: 500 }}
               placeholder="Domain name (e.g. Cooking EN→RU)"/>
        <select value={domain.target_lang || ''}
                onChange={e => onChange({ target_lang: e.target.value })}
                className="field" style={{ width: 130 }}>
          <option value="">any lang</option>
          {LANGS.filter(l => l.c !== 'auto').map(l => (
            <option key={l.c} value={l.c}>{l.n}</option>
          ))}
        </select>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', minWidth: 56, textAlign: 'right' }}>
          {Object.keys(terms).length} terms
        </span>
        <button className="btn-ghost" onClick={onRemove}
                style={{ padding: 4, color: 'var(--err)' }} title="Remove domain">
          {I.cancel}
        </button>
      </div>

      {expanded && (
        <div style={{ padding: 16 }}>
          {/* Triggers */}
          <div style={{ marginBottom: 16 }}>
            <div className="caps" style={{ marginBottom: 6 }}>
              Activate when source contains any of:
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
              {triggers.map(t => (
                <span key={t} style={{
                  padding: '3px 6px 3px 8px', borderRadius: 4,
                  background: 'var(--bg-2)', display: 'inline-flex', alignItems: 'center', gap: 4,
                  fontSize: 11,
                }}>
                  {t}
                  <button className="btn-ghost" onClick={() => removeTrigger(t)}
                          style={{ padding: '0 2px', fontSize: 12, color: 'var(--ink-3)' }}>×</button>
                </span>
              ))}
              <input value={newTrigger}
                     onChange={e => setNewTrigger(e.target.value)}
                     onKeyDown={e => e.key === 'Enter' && addTrigger()}
                     onBlur={addTrigger}
                     placeholder="+ trigger word"
                     className="field" style={{ flex: '0 1 160px', fontSize: 11, padding: '4px 8px' }}/>
            </div>
          </div>

          {/* Terms table */}
          <div className="caps" style={{ marginBottom: 6 }}>Term overrides</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 16px 1fr 32px',
              gap: 8, padding: '4px 8px',
              fontSize: 10, color: 'var(--ink-4)',
              fontFamily: 'var(--mono)',
            }}>
              <div>SOURCE</div>
              <div></div>
              <div>TRANSLATION</div>
              <div></div>
            </div>
            {Object.entries(terms).map(([src, dst]) => (
              <div key={src} style={{
                display: 'grid',
                gridTemplateColumns: '1fr 16px 1fr 32px',
                gap: 8, padding: '4px 0', alignItems: 'center',
              }}>
                <input defaultValue={src}
                       onBlur={e => {
                         const v = e.target.value.trim();
                         if (v && v !== src) updateTerm(src, v, dst);
                       }}
                       className="field" style={{ fontSize: 12 }}/>
                <div style={{ textAlign: 'center', color: 'var(--ink-4)' }}>→</div>
                <input defaultValue={dst}
                       onBlur={e => updateTerm(src, src, e.target.value)}
                       className="field" style={{ fontSize: 12 }}/>
                <button className="btn-ghost" onClick={() => removeTerm(src)}
                        style={{ padding: 4, color: 'var(--err)' }}>{I.cancel}</button>
              </div>
            ))}
            {/* New term row */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 16px 1fr 32px',
              gap: 8, padding: '4px 0', alignItems: 'center',
              borderTop: '1px dashed var(--line)', marginTop: 6, paddingTop: 10,
            }}>
              <input value={newSrc} onChange={e => setNewSrc(e.target.value)}
                     onKeyDown={e => e.key === 'Enter' && addTerm()}
                     placeholder="Source term"
                     className="field" style={{ fontSize: 12 }}/>
              <div style={{ textAlign: 'center', color: 'var(--ink-4)' }}>→</div>
              <input value={newDst} onChange={e => setNewDst(e.target.value)}
                     onKeyDown={e => e.key === 'Enter' && addTerm()}
                     placeholder="Translation"
                     className="field" style={{ fontSize: 12 }}/>
              <button className="btn-ghost" onClick={addTerm}
                      style={{ padding: 4, color: 'var(--accent)' }}
                      disabled={!newSrc.trim() || !newDst.trim()}>+</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


