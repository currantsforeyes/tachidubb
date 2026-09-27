// Home view — upload + configure form
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useRef, useMemo } = React;
import { LANGS, WHISPER_MODELS, _lsGet, _lsSet } from '../constants';
import { I } from '../icons';
import { mountSphere } from '../sphere';
import { Field, FileSlot, SectionHeader, Select, Toggle } from '../ui';

// ── Quick-test form — short clip × N languages ─────────────────────
// `kind` ∈ 'quick' | 'showcase' — same form structure, slightly different
// copy. Quick test = N separate dubbed videos for A/B comparison.
// Showcase = N segments stitched into one continuous video that cycles
// through the languages with a small corner badge.
export function QuickTestForm({
  kind = 'quick',
  mode, setMode, videoFile, setVideoFile, ytUrl, setYtUrl,
  refFile, voicePreset, ttsSpeed,
  trimSeconds, setTrimSeconds, langs, setLangs,
  onSubmit, submitting, error,
}) {
  const isShowcase = kind === 'showcase';
  const TRIM_STOPS = [30, 60, 90, 120];
  const DEFAULT_LANGS = ['es', 'fr', 'de', 'ja', 'pt'];
  const pickableLangs = LANGS.filter(l => l.c !== 'auto');

  const toggleLang = (code) => {
    if (langs.includes(code)) {
      if (langs.length > 2) setLangs(langs.filter(c => c !== code));
    } else {
      if (langs.length < 6) setLangs([...langs, code]);
    }
  };

  const estMinutes = Math.max(1, Math.round((langs.length * trimSeconds * 0.8) / 60));
  const sourceReady = (mode === 'file' && videoFile) || (mode === 'url' && ytUrl.trim());
  const langsOk = langs.length >= 2 && langs.length <= 6;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Source — file or URL */}
      <div>
        <div className="caps" style={{ marginBottom: 8 }}>
          {isShowcase ? 'Source · multilingual showcase reel' : 'Source · short clip'}
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <button className={'btn ' + (mode === 'file' ? 'btn-primary' : '')}
                  onClick={() => setMode('file')}>File</button>
          <button className={'btn ' + (mode === 'url' ? 'btn-primary' : '')}
                  onClick={() => setMode('url')}>URL</button>
        </div>
        {mode === 'file' ? (
          <input type="file" accept="video/*"
                 onChange={e => setVideoFile(e.target.files?.[0] || null)}
                 className="field"/>
        ) : (
          <input className="field" placeholder="https://youtube.com/watch?v=…"
                 value={ytUrl} onChange={e => setYtUrl(e.target.value)}/>
        )}
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 6 }}>
          {isShowcase
            ? `Source will be trimmed to the first ${trimSeconds}s, then split into ${langs.length} language segments (sentence-aligned) and stitched into one video.`
            : `Source will be trimmed to the first ${trimSeconds}s before dubbing.`}
        </div>
      </div>

      {/* Trim slider — discrete stops */}
      <div>
        <div className="caps" style={{ marginBottom: 8 }}>Trim duration</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {TRIM_STOPS.map(s => (
            <button key={s}
              onClick={() => setTrimSeconds(s)}
              className={'btn ' + (trimSeconds === s ? 'btn-primary' : '')}
              style={{ flex: 1 }}>
              {s}s
            </button>
          ))}
        </div>
      </div>

      {/* Language chips */}
      <div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
          <div className="caps">Target languages · {langs.length} of 2–6</div>
          <div style={{ flex: 1 }}/>
          <button className="btn-ghost"
                  style={{ fontSize: 11, color: 'var(--ink-3)' }}
                  onClick={() => setLangs(DEFAULT_LANGS)}>
            Reset to defaults
          </button>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {pickableLangs.map(l => {
            const on = langs.includes(l.c);
            const disabled = !on && langs.length >= 6;
            return (
              <button key={l.c}
                onClick={() => toggleLang(l.c)}
                disabled={disabled}
                style={{
                  padding: '6px 10px', borderRadius: 4,
                  background: on ? 'var(--accent)' : 'var(--bg-1)',
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
        {!langsOk && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--err)', marginTop: 6 }}>
            Pick 2–6 languages.
          </div>
        )}
      </div>

      {/* Runtime estimate */}
      <div style={{ padding: 12, background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 6 }}>
        <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          Estimated total runtime: ~{estMinutes} min
          ({langs.length} jobs × {trimSeconds}s clip, sequential on the GPU queue
          {isShowcase ? ' · +~10s for stitch step at the end' : ''})
        </div>
        {isShowcase && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 6, lineHeight: 1.5 }}>
            Each language gets ≈{Math.round(trimSeconds / Math.max(langs.length, 1))}s
            of screen time, snapped to the nearest sentence end. A small
            <span style={{ display: 'inline-block', padding: '1px 6px', margin: '0 4px',
                           background: 'rgba(0,0,0,0.55)', color: '#fff',
                           borderRadius: 3, fontSize: 9 }}>· LL ·</span>
            badge in the top-right corner shows the current language.
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mono" style={{ fontSize: 11, color: 'var(--err)' }}>{error}</div>
      )}

      {/* Submit */}
      <button
        className="btn btn-primary"
        disabled={submitting || !sourceReady || !langsOk}
        onClick={onSubmit}
        style={{ width: '100%', justifyContent: 'center', padding: '12px 16px' }}>
        {submitting
          ? 'Submitting…'
          : !sourceReady
            ? (mode === 'file' ? 'Choose a video file' : 'Paste a URL')
            : (isShowcase
                ? `Build showcase reel ▸ ${langs.length} langs × ${trimSeconds}s`
                : `Start quick test ▸ ${langs.length} langs × ${trimSeconds}s`)}
      </button>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// HOME VIEW — upload + configure form, real backend wiring
// One long editorial form (per scoping survey).
// ═══════════════════════════════════════════════════════════════════
export function HomeView({ system, voicePresets, sphereOn, onJobSubmitted }) {
  // ── Form state with localStorage persistence (all keys match old UI) ──
  const [mode, setMode] = useState('url');             // 'file' | 'url'
  const [batchMode, setBatchMode] = useState(false);
  const [quickTestMode, setQuickTestMode] = useState(false);
  const [showcaseMode, setShowcaseMode] = useState(false);
  // Mutually exclusive — flipping one resets the others
  const switchTo = (target) => {
    setBatchMode(target === 'batch');
    setQuickTestMode(target === 'quick');
    setShowcaseMode(target === 'showcase');
  };
  const [videoFile, setVideoFile] = useState(null);
  const [ytUrl, setYtUrl] = useState('');
  const [refFile, setRefFile] = useState(null);

  const [batchFiles, setBatchFiles] = useState([]);    // File[]
  const [batchUrls, setBatchUrls] = useState('');      // newline-separated
  const [batchLabel, setBatchLabel] = useState('');
  const [batchSchedule, setBatchSchedule] = useState('');

  const [srcLang, setSrcLang] = useState(() => _lsGet('srcLang', 'auto'));
  const [tgtLang, setTgtLang] = useState(() => _lsGet('tgtLang', 'ru'));
  const [model, setModel] = useState(() => _lsGet('model', 'aya-expanse:8b'));
  const [whisperModel, setWhisperModel] = useState(() => _lsGet('whisperModel', 'large-v3'));
  const [speakerMode, setSpeakerMode] = useState(() => _lsGet('speakerMode', 'main'));
  const [speakerCount, setSpeakerCount] = useState(() => _lsGet('speakerCount', '0'));
  const [voicePreset, setVoicePreset] = useState(() => _lsGet('voicePreset', 'auto'));
  const [voiceStyle, setVoiceStyle] = useState('');
  const [ttsSpeed, setTtsSpeed] = useState(() => _lsGet('ttsSpeed', 'balanced'));
  const [contextHint, setContextHint] = useState(() => _lsGet('contextHint', ''));

  const [keepBg, setKeepBg] = useState(() => _lsGet('keepBg', false));
  const [autoDenoise, setAutoDenoise] = useState(() => _lsGet('autoDenoise', false));
  const [lipSync, setLipSync] = useState(() => _lsGet('lipSync', false));
  const [narrationMode, setNarrationMode] = useState(() => _lsGet('narrationMode', false));
  const [lipStatus, setLipStatus] = useState(null);
  useEffect(() => {
    fetch('/api/lip_sync/status').then(r => r.json()).then(setLipStatus).catch(() => {});
  }, []);
  const [llmRegroup, setLlmRegroup] = useState(() => _lsGet('llmRegroup', false));
  const [wizardReview, setWizardReview] = useState(() => _lsGet('wizardReview', false));

  // Quick-test mode state — independent from single/batch state above
  const [qtTrimSeconds, setQtTrimSeconds] = useState(() => _lsGet('qtTrim', 60));
  const [qtLangs, setQtLangs] = useState(() => {
    const stored = _lsGet('qtLangs', null);
    return Array.isArray(stored) && stored.length >= 2 ? stored : ['es', 'fr', 'de', 'ja', 'pt'];
  });
  useEffect(() => { _lsSet('qtTrim', qtTrimSeconds); }, [qtTrimSeconds]);
  useEffect(() => { _lsSet('qtLangs', qtLangs); }, [qtLangs]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Persist all preferences
  useEffect(() => { _lsSet('srcLang', srcLang); }, [srcLang]);
  useEffect(() => { _lsSet('tgtLang', tgtLang); }, [tgtLang]);
  useEffect(() => { _lsSet('model', model); }, [model]);
  useEffect(() => { _lsSet('whisperModel', whisperModel); }, [whisperModel]);
  useEffect(() => { _lsSet('speakerMode', speakerMode); }, [speakerMode]);
  useEffect(() => { _lsSet('speakerCount', speakerCount); }, [speakerCount]);
  useEffect(() => { _lsSet('voicePreset', voicePreset); }, [voicePreset]);
  useEffect(() => { _lsSet('ttsSpeed', ttsSpeed); }, [ttsSpeed]);
  useEffect(() => { _lsSet('contextHint', contextHint); }, [contextHint]);
  useEffect(() => { _lsSet('keepBg', keepBg); }, [keepBg]);
  useEffect(() => { _lsSet('autoDenoise', autoDenoise); }, [autoDenoise]);
  useEffect(() => { _lsSet('lipSync', lipSync); }, [lipSync]);
  useEffect(() => { _lsSet('narrationMode', narrationMode); }, [narrationMode]);
  useEffect(() => { _lsSet('llmRegroup', llmRegroup); }, [llmRegroup]);
  useEffect(() => { _lsSet('wizardReview', wizardReview); }, [wizardReview]);

  // Installed Ollama models (from /api/system response). Fall back to a known set
  // if /api/system hasn't returned yet so the user can still pick something.
  const installedModels = useMemo(() => {
    const m = system?.ollama?.models;
    if (m && m.length) return m.map(x => typeof x === 'string' ? x : x.name).filter(Boolean);
    return ['aya-expanse:8b', 'qwen2.5:7b', 'gemma3:12b', 'llama3.2:3b'];
  }, [system]);

  // CTA label — depends on mode and schedule
  const submitLabel = (() => {
    if (submitting) return 'Submitting…';
    if (batchMode) {
      const c = batchFiles.length + batchUrls.split('\n').filter(l => l.trim()).length;
      if (c === 0) return 'Add at least one source';
      if (batchSchedule) return `Schedule ${c} videos for ${new Date(batchSchedule).toLocaleString()}`;
      return `Queue ${c} videos now`;
    }
    if (mode === 'file' && !videoFile) return 'Choose a video file';
    if (mode === 'url' && !ytUrl.trim()) return 'Paste a URL';
    return 'Start dubbing';
  })();

  const canSubmit = !submitting && (
    batchMode
      ? (batchFiles.length + batchUrls.split('\n').filter(l => l.trim()).length) > 0
      : (mode === 'file' ? !!videoFile : !!ytUrl.trim())
  );

  // ── Submit handlers ─────────────────────────────────────────────
  const submitSingle = async () => {
    setError(null); setSubmitting(true);
    const fd = new FormData();
    if (mode === 'file' && videoFile) fd.append('video', videoFile);
    else if (mode === 'url' && ytUrl) fd.append('source', ytUrl);
    if (refFile) fd.append('reference', refFile);
    fd.append('source_lang', srcLang);
    fd.append('target_lang', tgtLang);
    fd.append('model', model);
    fd.append('keep_bg', keepBg);
    fd.append('whisper_model', whisperModel);
    fd.append('speaker_mode', speakerMode);
    fd.append('speaker_count', speakerCount);
    fd.append('context_hint', contextHint);
    fd.append('voice_style', voiceStyle);
    fd.append('voice_preset', voicePreset);
    fd.append('tts_speed', ttsSpeed);
    fd.append('wizard_mode', wizardReview ? 'review_translation' : 'auto');
    fd.append('auto_denoise', autoDenoise);
    fd.append('llm_regroup', llmRegroup);
    fd.append('lip_sync', lipSync);
    fd.append('narration_mode', narrationMode);
    try {
      const r = await fetch('/api/dub', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.job_id) onJobSubmitted(d.job_id);
      else setError(d.error || d.detail || 'Submit failed');
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const submitBatch = async () => {
    setError(null); setSubmitting(true);
    const fd = new FormData();
    batchFiles.forEach(f => fd.append('videos', f));
    if (batchUrls.trim()) fd.append('sources', batchUrls.trim());
    if (refFile) fd.append('reference', refFile);
    fd.append('source_lang', srcLang);
    fd.append('target_lang', tgtLang);
    fd.append('model', model);
    fd.append('keep_bg', keepBg);
    fd.append('whisper_model', whisperModel);
    fd.append('speaker_mode', speakerMode);
    fd.append('context_hint', contextHint);
    fd.append('voice_style', voiceStyle);
    fd.append('voice_preset', voicePreset);
    fd.append('tts_speed', ttsSpeed);
    fd.append('wizard_mode', 'auto');
    fd.append('auto_denoise', autoDenoise);
    fd.append('llm_regroup', llmRegroup);
    fd.append('batch_label', batchLabel || `Batch ${new Date().toLocaleString()}`);
    if (batchSchedule) {
      const ts = Math.floor(new Date(batchSchedule).getTime() / 1000);
      if (ts > Math.floor(Date.now() / 1000) + 10) fd.append('scheduled_at', String(ts));
    }
    try {
      const r = await fetch('/api/dub/batch', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.batch_id || d.job_ids) onJobSubmitted(null);
      else setError(d.error || d.detail || 'Batch submit failed');
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const submitQuickTest = async () => {
    setError(null); setSubmitting(true);
    const fd = new FormData();
    if (mode === 'file' && videoFile) fd.append('video', videoFile);
    else if (mode === 'url' && ytUrl) fd.append('source', ytUrl);
    if (refFile) fd.append('reference', refFile);
    fd.append('trim_seconds', String(qtTrimSeconds));
    fd.append('target_langs', qtLangs.join(','));
    fd.append('source_lang', srcLang);
    fd.append('model', model);
    fd.append('whisper_model', whisperModel);
    fd.append('speaker_mode', speakerMode);
    fd.append('voice_preset', voicePreset);
    fd.append('voice_style', voiceStyle);
    fd.append('tts_speed', ttsSpeed);
    fd.append('keep_bg', keepBg);
    fd.append('auto_denoise', autoDenoise);
    fd.append('context_hint', contextHint);
    try {
      const r = await fetch('/api/quick_test', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.batch_id || d.job_ids) onJobSubmitted(null);
      else setError(d.error || d.detail || 'Quick-test submit failed');
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const submitShowcase = async () => {
    // Showcase reuses the Quick Test form state (qtTrimSeconds, qtLangs)
    // but posts to /api/showcase, which triggers stitch-into-one after
    // all per-language dubs finish.
    setError(null); setSubmitting(true);
    const fd = new FormData();
    if (mode === 'file' && videoFile) fd.append('video', videoFile);
    else if (mode === 'url' && ytUrl) fd.append('source', ytUrl);
    if (refFile) fd.append('reference', refFile);
    fd.append('trim_seconds', String(qtTrimSeconds));
    fd.append('target_langs', qtLangs.join(','));
    fd.append('source_lang', srcLang);
    fd.append('model', model);
    fd.append('whisper_model', whisperModel);
    fd.append('speaker_mode', speakerMode);
    fd.append('voice_preset', voicePreset);
    fd.append('voice_style', voiceStyle);
    fd.append('tts_speed', ttsSpeed);
    fd.append('keep_bg', keepBg);
    fd.append('auto_denoise', autoDenoise);
    fd.append('context_hint', contextHint);
    try {
      const r = await fetch('/api/showcase', { method: 'POST', body: fd });
      const d = await r.json();
      if (d.batch_id || d.job_ids) onJobSubmitted(null);
      else setError(d.error || d.detail || 'Showcase submit failed');
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const submit = () => {
    if (showcaseMode) return submitShowcase();
    if (quickTestMode) return submitQuickTest();
    if (batchMode) return submitBatch();
    return submitSingle();
  };

  // Cmd/Ctrl+Enter shortcut
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && canSubmit) {
        e.preventDefault();
        submit();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  return (
    <div style={{ flex: 1, overflow: 'auto', position: 'relative', background: 'var(--bg)' }}>
      {/* Hero with sphere on the right */}
      <Hero sphereOn={sphereOn}/>

      {/* Form — narrow editorial column */}
      <div style={{ maxWidth: 760, margin: '0 auto', padding: '0 32px 80px' }}>

        {/* Error banner */}
        {error && (
          <div style={{
            margin: '0 0 24px',
            padding: '12px 14px',
            background: 'oklch(0.7 0.2 25 / 0.08)',
            border: '1px solid oklch(0.7 0.2 25 / 0.3)',
            borderRadius: 8, display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span style={{ color: 'var(--err)' }}>{I.cancel}</span>
            <div style={{ flex: 1, fontSize: 12.5, color: 'var(--ink)' }}>{error}</div>
            <button className="btn-ghost" style={{ padding: 4, color: 'var(--ink-3)' }} onClick={() => setError(null)}>{I.cancel}</button>
          </div>
        )}

        {/* 01 SOURCE */}
        <SectionHeader index={1} title="Source media" subtitle="One file or batch · file upload or URL"/>

        {/* Single vs Batch toggle */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
          <ModeBtn active={!batchMode && !quickTestMode && !showcaseMode} onClick={() => switchTo('single')} label="Single video"/>
          <ModeBtn active={batchMode}     onClick={() => switchTo('batch')}    label="Batch — many videos"/>
          <ModeBtn active={quickTestMode} onClick={() => switchTo('quick')}    label="Quick test · multi-lang"/>
          <ModeBtn active={showcaseMode}  onClick={() => switchTo('showcase')} label="Showcase · stitched reel"/>
        </div>

        {showcaseMode && (
          <QuickTestForm
            kind="showcase"
            mode={mode} setMode={setMode}
            videoFile={videoFile} setVideoFile={setVideoFile}
            ytUrl={ytUrl} setYtUrl={setYtUrl}
            refFile={refFile}
            voicePreset={voicePreset}
            ttsSpeed={ttsSpeed}
            trimSeconds={qtTrimSeconds} setTrimSeconds={setQtTrimSeconds}
            langs={qtLangs} setLangs={setQtLangs}
            onSubmit={submitShowcase}
            submitting={submitting}
            error={error}/>
        )}

        {quickTestMode && (
          <QuickTestForm
            mode={mode} setMode={setMode}
            videoFile={videoFile} setVideoFile={setVideoFile}
            ytUrl={ytUrl} setYtUrl={setYtUrl}
            refFile={refFile}
            voicePreset={voicePreset}
            ttsSpeed={ttsSpeed}
            trimSeconds={qtTrimSeconds} setTrimSeconds={setQtTrimSeconds}
            langs={qtLangs} setLangs={setQtLangs}
            onSubmit={submitQuickTest}
            submitting={submitting}
            error={error}
          />
        )}

        {!quickTestMode && !showcaseMode && (<>
        {!batchMode && (
          <SingleSource
            mode={mode} setMode={setMode}
            videoFile={videoFile} setVideoFile={setVideoFile}
            ytUrl={ytUrl} setYtUrl={setYtUrl}
          />
        )}
        {batchMode && (
          <BatchSource
            files={batchFiles} setFiles={setBatchFiles}
            urls={batchUrls} setUrls={setBatchUrls}
          />
        )}

        {/* 02 LANGUAGES & MODELS */}
        <SectionHeader index={2} title="Languages & models"/>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <Field label="Source language">
            <Select value={srcLang} onChange={setSrcLang}>
              {LANGS.map(l => <option key={l.c} value={l.c} style={{ background: '#16161c' }}>{l.n}</option>)}
            </Select>
          </Field>
          <Field label="Target language">
            <Select value={tgtLang} onChange={setTgtLang}>
              {LANGS.filter(l => l.c !== 'auto').map(l => <option key={l.c} value={l.c} style={{ background: '#16161c' }}>{l.n}</option>)}
            </Select>
          </Field>
          <Field label="Translation model" hint="Pulled via Ollama. Manage in System →">
            <Select value={model} onChange={setModel}>
              {installedModels.map(m => <option key={m} value={m} style={{ background: '#16161c' }}>{m}</option>)}
            </Select>
          </Field>
          <Field label="Whisper model" hint="large-v3 = best quality. small = clean studio audio only.">
            <Select value={whisperModel} onChange={setWhisperModel}>
              {WHISPER_MODELS.map(m => <option key={m.id} value={m.id} style={{ background: '#16161c' }}>{m.name} · {m.size} · {m.detail}</option>)}
            </Select>
          </Field>
        </div>

        {/* 03 VOICE */}
        <SectionHeader index={3} title="Voice"/>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
          {[
            ['main', 'Main speaker only', 'Best for solo videos · one consistent voice'],
            ['all',  'All speakers',       'Clone every detected voice'],
          ].map(([v, label, hint]) => (
            <button key={v} onClick={() => setSpeakerMode(v)} style={{
              padding: '10px 14px', borderRadius: 6, textAlign: 'left',
              cursor: 'pointer', transition: 'all 0.15s',
              background: speakerMode === v ? 'var(--bg-2)' : 'var(--bg-1)',
              border: '1px solid ' + (speakerMode === v ? 'var(--accent)' : 'var(--line)'),
              color: 'var(--ink)',
            }}>
              <div style={{ fontSize: 12.5, fontWeight: 500 }}>{label}</div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 2 }}>{hint}</div>
            </button>
          ))}
        </div>
        {speakerMode === 'all' && (
          <Field label="Known speaker count" hint="Use when the cast is known. Auto can merge short, fast dialogue.">
            <Select value={speakerCount} onChange={setSpeakerCount}>
              <option value="0" style={{ background: '#16161c' }}>auto-detect</option>
              {[2, 3, 4, 5, 6].map(n => <option key={n} value={String(n)} style={{ background: '#16161c' }}>{n} speakers</option>)}
            </Select>
          </Field>
        )}
        <Field label="Voice preset" hint="Auto-clone uses each speaker's extracted reference. Pick a preset to override.">
          <Select value={voicePreset} onChange={setVoicePreset}>
            <option value="auto" style={{ background: '#16161c' }}>auto · clone source</option>
            {voicePresets.map(p => (
              <option key={p.id} value={p.id} style={{ background: '#16161c' }}>
                {p.name}{p.style ? ' · ' + p.style : ''}{p.type === 'file' ? ' · file' : ''}
              </option>
            ))}
          </Select>
        </Field>
        <div style={{ marginTop: 14 }}>
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
        <div style={{ marginTop: 14 }}>
          <Field label="Voice reference (optional)" hint="WAV or MP3. 10-30s of clean speech.">
            <FileSlot file={refFile} setFile={setRefFile} accept="audio/*,video/*"/>
          </Field>
        </div>

        {/* 04 ADVANCED */}
        <SectionHeader index={4} title="Advanced"/>
        <Toggle value={keepBg}     onChange={setKeepBg}     label="Keep background audio (music / SFX)" hint="Uses audio-separator. Install required — see System."/>
        <Toggle value={autoDenoise} onChange={setAutoDenoise} label="Auto-denoise audio" hint="+3-5s · ON for noisy footage (mat sounds, crowd, AC hum) · OFF for clean studio audio"/>
        <Toggle value={lipSync} onChange={setLipSync}
                disabled={lipStatus && !lipStatus.installed}
                label={'Sync lips with MuseTalk' + (lipStatus && !lipStatus.installed ? ' (not installed)' : '')}
                hint={lipStatus && !lipStatus.installed
                  ? 'MuseTalk not detected. Install via System tab to enable.'
                  : 'Auto-runs MuseTalk after dubbing. Best for talking-head footage; fails on action shots or far-away faces. Roughly real-time on a modern GPU.'}/>
        <Toggle value={narrationMode} onChange={setNarrationMode}
                label="Narrator mode — one voice for the whole video"
                hint="Skips speaker detection and reads everything in a single (cloned) voice — best for localized narration rather than matching each speaker. Uses your uploaded/preset voice when set."/>
        <Toggle value={llmRegroup}  onChange={setLlmRegroup}  label="LLM segment regrouping" hint="+20-40s on long videos · fixes mid-sentence breaks · best for podcasts, lectures, seminars"/>
        <Toggle value={wizardReview} onChange={setWizardReview} label="Wizard mode — pause for review" hint="Pause after translation so you can edit segments and replace voice references."/>

        <div style={{ marginTop: 14 }}>
          <Field label="Translation context (optional)" hint="A short hint for the LLM. Examples: 'BJJ grappling seminar', 'tech podcast', 'cooking show'.">
            <input
              className="field"
              value={contextHint}
              onChange={e => setContextHint(e.target.value)}
              placeholder="e.g. BJJ seminar, tech podcast"
            />
          </Field>
        </div>

        {/* 05 BATCH-ONLY OPTIONS */}
        {batchMode && (
          <>
            <SectionHeader index={5} title="Batch options"/>
            <Field label="Batch label (optional)">
              <input
                className="field"
                value={batchLabel}
                onChange={e => setBatchLabel(e.target.value)}
                placeholder="e.g. BJJ Course · Week 1"
              />
            </Field>
            <div style={{ marginTop: 14 }}>
              <Field label="Schedule start (optional)" hint="Empty = start now. Set to run overnight on cheap GPU hours.">
                <input
                  className="field"
                  type="datetime-local"
                  value={batchSchedule}
                  onChange={e => setBatchSchedule(e.target.value)}
                />
              </Field>
            </div>
          </>
        )}

        {/* SUBMIT */}
        <div style={{ marginTop: 36, display: 'flex', gap: 10, alignItems: 'center' }}>
          <button onClick={submit} disabled={!canSubmit} className="btn btn-primary" style={{
            flex: 1, justifyContent: 'center', padding: '12px 16px', fontSize: 13,
          }}>
            {submitLabel} {canSubmit && I.arrow}
          </button>
          <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>⌘↵</span>
        </div>
        </>)}
      </div>
    </div>
  );
}

// ── Hero with sphere ──
export function Hero({ sphereOn }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !sphereOn) return;
    return mountSphere(ref.current, { variant: 'idle', size: 220 });
  }, [sphereOn]);

  return (
    <div style={{
      maxWidth: 760, margin: '0 auto',
      padding: '52px 32px 32px',
      display: 'flex', alignItems: 'flex-start', gap: 36,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="caps" style={{ marginBottom: 12 }}>New dub</div>
        <h1 className="serif" style={{
          fontSize: 48, lineHeight: 1.02, letterSpacing: '-0.02em', marginBottom: 14,
        }}>
          Voice it back, <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>line by line</span>.
        </h1>
        <div style={{ fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.55, maxWidth: 480 }}>
          Local, GPU-accelerated dubbing. WhisperX listens, Ollama translates, VoxCPM speaks.
          Drop a file or paste a URL below.
        </div>
      </div>
      {sphereOn && (
        <div ref={ref} style={{ width: 220, height: 220, flexShrink: 0, pointerEvents: 'none' }}/>
      )}
    </div>
  );
}

// ── Mode button (single / batch) ──
export function ModeBtn({ active, onClick, label }) {
  return (
    <button onClick={onClick} style={{
      padding: '8px 14px', fontSize: 12.5, fontWeight: 500,
      borderRadius: 6,
      border: '1px solid ' + (active ? 'var(--accent)' : 'var(--line)'),
      background: active ? 'var(--bg-2)' : 'var(--bg-1)',
      color: active ? 'var(--ink)' : 'var(--ink-2)',
      cursor: 'pointer',
    }}>{label}</button>
  );
}

// ── Single source: file or URL toggle ──
export function SingleSource({ mode, setMode, videoFile, setVideoFile, ytUrl, setYtUrl }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        <SubTab active={mode === 'file'} onClick={() => setMode('file')} label="File"/>
        <SubTab active={mode === 'url'}  onClick={() => setMode('url')}  label="URL"/>
      </div>
      {mode === 'file' && <FileSlot file={videoFile} setFile={setVideoFile} accept="video/*,audio/*"/>}
      {mode === 'url' && (
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{ display: 'flex', alignItems: 'center', padding: '0 12px', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRight: 'none', borderRadius: '6px 0 0 6px', color: 'var(--ink-3)' }}>
            {I.link}
          </span>
          <input
            className="field"
            value={ytUrl}
            onChange={e => setYtUrl(e.target.value)}
            placeholder="https://youtube.com/watch?v=…"
            style={{ borderRadius: '0 6px 6px 0' }}
          />
        </div>
      )}
    </div>
  );
}

export function SubTab({ active, onClick, label }) {
  return (
    <button onClick={onClick} style={{
      padding: '5px 12px', fontSize: 11, fontWeight: 500,
      borderRadius: 5,
      background: active ? 'var(--bg-2)' : 'transparent',
      color: active ? 'var(--ink)' : 'var(--ink-3)',
      cursor: 'pointer',
    }}>{label}</button>
  );
}

// ── Batch sources ──
export function BatchSource({ files, setFiles, urls, setUrls }) {
  const inputRef = useRef(null);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 12 }}>
      {/* Files */}
      <div>
        <div className="caps" style={{ marginBottom: 6 }}>Files · {files.length}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {files.map((f, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '8px 12px',
              background: 'var(--bg-2)', border: '1px solid var(--line)',
              borderRadius: 6,
            }}>
              <span style={{ color: 'var(--accent)' }}>{I.check}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
                <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>{(f.size / (1024 * 1024)).toFixed(1)} MB</div>
              </div>
              <button className="btn-ghost" style={{ padding: 4, color: 'var(--ink-3)' }} onClick={() => setFiles(files.filter((_, j) => j !== i))}>{I.cancel}</button>
            </div>
          ))}
          <input ref={inputRef} type="file" multiple accept="video/*,audio/*" style={{ display: 'none' }}
            onChange={e => { setFiles([...files, ...Array.from(e.target.files)]); e.target.value = ''; }}/>
          <button onClick={() => inputRef.current?.click()} style={{
            padding: '8px 10px', fontSize: 12, color: 'var(--ink-3)',
            background: 'transparent', border: '1px dashed var(--line-2)',
            borderRadius: 6, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center',
          }}>{I.plus} Add files</button>
        </div>
      </div>

      {/* URLs */}
      <Field label="URLs · one per line" hint="YouTube, Vimeo, direct mp4 — anything yt-dlp handles.">
        <textarea
          className="field"
          value={urls}
          onChange={e => setUrls(e.target.value)}
          placeholder={`https://youtube.com/watch?v=…\nhttps://youtube.com/watch?v=…`}
          style={{ resize: 'vertical', minHeight: 80, fontFamily: 'var(--mono)', fontSize: 11.5 }}
        />
      </Field>
    </div>
  );
}

