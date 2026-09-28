// Editor view — DAW-style dialogue timeline workspace
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useRef, useCallback, useMemo } = React;
import { fmtAge, fmtSec } from '../constants';
import { I } from '../icons';
import { Select } from '../ui';

// ═══════════════════════════════════════════════════════════════════
// EDITOR VIEW — dedicated source video and dubbed-audio timing workspace.
// ═══════════════════════════════════════════════════════════════════
export function EditorView({ jobs, selectedJobId, onPickJob, onSwitchToHome }) {
  const completedJobs = useMemo(
    () => jobs.filter(j => j.status === 'complete').sort((a, b) => (b.completed_at || b.created || 0) - (a.completed_at || a.created || 0)),
    [jobs]
  );
  const job = useMemo(() => {
    if (selectedJobId) return completedJobs.find(j => j.id === selectedJobId) || completedJobs[0];
    return completedJobs[0];
  }, [completedJobs, selectedJobId]);

  if (!job) {
    return <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, padding: 40, background: 'var(--bg)' }}>
      <div className="caps">No completed jobs yet</div>
      <div className="serif" style={{ fontSize: 32, letterSpacing: '-0.015em', textAlign: 'center', maxWidth: 480 }}>Nothing to <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>edit</span> yet.</div>
      <div style={{ fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 390, lineHeight: 1.5 }}>Finish a dub first, then return here to line up its generated dialogue with the original video and audio.</div>
      <button onClick={onSwitchToHome} className="btn btn-primary" style={{ marginTop: 8 }}>{I.arrow} Start a dub</button>
    </div>;
  }

  return <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg)' }}>
    <div style={{ padding: '18px 22px 44px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="caps" style={{ marginBottom: 6 }}>Dedicated timeline workspace</div>
          <div className="serif" style={{ fontSize: 26, lineHeight: 1.05, letterSpacing: '-0.015em' }}>Dialogue <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>editor</span></div>
        </div>
        {completedJobs.length > 1 && <div style={{ width: 300, flexShrink: 0 }}><Select value={job.id} onChange={onPickJob}>
          {completedJobs.slice(0, 20).map(j => <option key={j.id} value={j.id} style={{ background: '#16161c' }}>{(j.source_label || j.source || j.id).slice(0, 50)} · {fmtAge(j.completed_at || j.created)}</option>)}
        </Select></div>}
      </div>
      <TimelinePanel job={job} onApplied={() => {}}/>
    </div>
  </div>;
}

export const ED = {
  toStart: <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M3 3h1.6v10H3zM13 3.6v8.8L6 8z"/></svg>,
  prev:    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M11 3.6v8.8L4 8z"/></svg>,
  stop:    <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><rect x="3.5" y="3.5" width="9" height="9" rx="1"/></svg>,
  play:    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M4 3l9 5-9 5z"/></svg>,
  pause:   <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><rect x="3.5" y="3" width="3.4" height="10" rx="1"/><rect x="9.1" y="3" width="3.4" height="10" rx="1"/></svg>,
  next:    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M5 3.6v8.8L12 8z"/></svg>,
  toEnd:   <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M11.4 3h1.6v10h-1.6zM5 3.6v8.8L12 8z"/></svg>,
  pointer: <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M4 2.5l8 6.2-3.4.5 1.9 3.6-1.6.8-1.9-3.7L4.6 12z"/></svg>,
  razor:   <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M3 3l10 10M3 13L13 3"/><circle cx="4.6" cy="4.6" r="1.6"/><circle cx="11.4" cy="11.4" r="1.6"/></svg>,
  link:    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M6.5 9.5l3-3M4.6 11.4L3.4 12.6a2 2 0 01-2.8-2.8l1.2-1.2M11.4 4.6l1.2-1.2a2 2 0 012.8 2.8l-1.2 1.2"/></svg>,
  volume:  <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M3 6h2l3-2.6v9.2L5 10H3z"/><path d="M10.6 6.2a2.6 2.6 0 010 3.6" fill="none" stroke="currentColor" strokeWidth="1.3"/></svg>,
  dim:     <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M3 6h2l3-2.6v9.2L5 10H3z"/><path d="M10 6.5l4 3M14 6.5l-4 3" fill="none" stroke="currentColor" strokeWidth="1.3"/></svg>,
};

// HH:MM:SS:FF — the mock's big timecode readout (30 fps nominal).
export const fmtTimecode = (s, fps = 30) => {
  const v = Math.max(0, s || 0);
  const p = n => String(Math.floor(n)).padStart(2, '0');
  return `${p(v / 3600)}:${p((v % 3600) / 60)}:${p(v % 60)}:${p((v - Math.floor(v)) * fps)}`;
};

// "SPEAKER_00" -> "Speaker 1"
export const niceSpeaker = (spk) => {
  const raw = String(spk || '');
  const num = parseInt(raw.replace('SPEAKER_', ''), 10);
  return Number.isFinite(num) ? `Speaker ${num + 1}` : (raw || 'Speaker');
};

export function SMBtn({ active, onClick, label, title }) {
  return (
    <button onClick={onClick} title={title} style={{
      width: 20, height: 18, borderRadius: 3, fontSize: 9, fontWeight: 600,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      border: '1px solid ' + (active ? 'var(--accent)' : 'var(--line)'),
      background: active ? 'var(--accent)' : 'var(--bg-2)',
      color: active ? '#0a0a0d' : 'var(--ink-3)', cursor: 'pointer',
    }}>{label}</button>
  );
}

// Canvas waveform. `activeKey` is a JSON array of [start,end] ranges that are
// this speaker's own clips — everything else is drawn dimmed.
export function WaveformLane({ peaks, duration, pxPerSec, height = 56, activeKey = '', dim = false, color = 'oklch(0.88 0.18 125)' }) {
  const ref = useRef(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const w = Math.max(2, Math.round(duration * pxPerSec));
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(height * dpr);
    cv.style.width = w + 'px';
    cv.style.height = height + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, height);
    if (!peaks || !peaks.length) return;
    let active = null;
    try { active = activeKey ? JSON.parse(activeKey) : null; } catch { active = null; }
    const mid = height / 2;
    const step = w / peaks.length;
    for (let i = 0; i < peaks.length; i++) {
      const t = duration * (i / peaks.length);
      const on = !active || active.some(r => t >= r[0] && t <= r[1]);
      ctx.globalAlpha = (dim ? 0.14 : (on ? 0.9 : 0.22));
      ctx.fillStyle = color;
      const h = Math.max(1, peaks[i] * mid * 0.9);
      ctx.fillRect(i * step, mid - h, Math.max(1, step * 0.85), h * 2);
    }
    ctx.globalAlpha = 1;
  }, [peaks, duration, pxPerSec, height, activeKey, dim, color]);
  return <canvas ref={ref} style={{ display: 'block' }}/>;
}

export function TimelinePanel({ job, onApplied }) {
  const [timeline, setTimeline] = useState(null);
  const [dragging, setDragging] = useState(null);
  const [scrubbing, setScrubbing] = useState(false);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [loadFailed, setLoadFailed] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [tool, setTool] = useState('select');
  const [pxPerSec, setPxPerSec] = useState(26);
  const [speed, setSpeed] = useState(1);
  const [volume, setVolume] = useState(1);
  const [solo, setSolo] = useState(null);
  const [muted, setMuted] = useState({});
  const [videoMode, setVideoMode] = useState('dubbed');
  const [mixerOn, setMixerOn] = useState(false);
  const [stemState, setStemState] = useState('idle');
  const stemRef = useRef({});
  const railRef = useRef(null);
  const videoRef = useRef(null);

  useEffect(() => {
    let live = true;
    // Don't leave the editor on "Loading clips..." forever if the request
    // stalls (slow disk, server restart mid-flight) — fail visibly + Retry.
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 10000);
    setTimeline(null); setError(null); setLoadFailed(null); setPlayhead(0);
    setMixerOn(false); setStemState('idle');
    fetch(`/api/dub/${job.id}/timeline`, { signal: ctrl.signal }).then(r => r.json()).then(d => {
      if (!live) return;
      if (d.error) setLoadFailed(d.error); else setTimeline(d);
    }).catch(e => {
      if (!live) return;
      setLoadFailed(e && e.name === 'AbortError'
        ? 'Timeline request timed out after 10s.'
        : 'Could not load the timeline.');
    }).finally(() => window.clearTimeout(timer));
    return () => { live = false; ctrl.abort(); window.clearTimeout(timer); };
  }, [job.id, reloadKey]);

  const duration = timeline ? Math.max(timeline.duration || 1, 1) : 1;
  const totalWidth = Math.max(320, Math.round(duration * pxPerSec));

  const speakers = useMemo(() => {
    if (!timeline) return [];
    return [...new Set(timeline.segments.map(s => s.speaker || 'SPEAKER_00'))].sort();
  }, [timeline]);

  const segsBySpeaker = useMemo(() => {
    const m = {};
    (timeline?.segments || []).forEach(s => {
      const k = s.speaker || 'SPEAKER_00';
      (m[k] = m[k] || []).push(s);
    });
    return m;
  }, [timeline]);

  const ticks = useMemo(() => {
    const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    const step = steps.find(s => s * pxPerSec >= 74) || 600;
    const out = [];
    for (let i = 0; i * step <= duration + 1e-6; i++) out.push(i * step);
    return out;
  }, [duration, pxPerSec]);

  useEffect(() => { if (videoRef.current) videoRef.current.playbackRate = speed; }, [speed, timeline]);
  useEffect(() => { if (videoRef.current) videoRef.current.volume = volume; }, [volume, timeline]);

  // Per-speaker stems (solo / mute). Stems are derived server-side from the
  // existing per-segment clips, so switching the mixer on costs no
  // re-synthesis. Until it is on, the video plays its own dubbed audio and the
  // S / M buttons are purely visual.
  useEffect(() => {
    return () => {
      Object.values(stemRef.current).forEach(a => { try { a.pause(); a.src = ''; } catch {} });
      stemRef.current = {};
    };
  }, [job.id]);

  const enableMixer = useCallback(async () => {
    if (mixerOn || stemState === 'loading' || !timeline || !speakers.length) return;
    setStemState('loading');
    const made = {};
    try {
      await Promise.all(speakers.map(spk => new Promise((resolve, reject) => {
        const a = new Audio(`/api/dub/${job.id}/stem/${spk}/audio`);
        a.preload = 'auto';
        made[spk] = a;
        a.addEventListener('canplaythrough', () => resolve(), { once: true });
        a.addEventListener('error', () => reject(new Error('stem unavailable')), { once: true });
        setTimeout(resolve, 10000);
        a.load();
      })));
      stemRef.current = made;
      const v = videoRef.current;
      if (v) {
        v.muted = true;
        Object.values(made).forEach(a => { a.currentTime = v.currentTime; a.volume = 0; if (!v.paused) a.play().catch(() => {}); });
      }
      setMixerOn(true); setStemState('ready');
    } catch (e) {
      Object.values(made).forEach(a => { try { a.pause(); } catch {} });
      setStemState('error');
    }
  }, [mixerOn, stemState, timeline, speakers, job.id]);

  const disableMixer = () => {
    Object.values(stemRef.current).forEach(a => { try { a.pause(); } catch {} });
    if (videoRef.current) videoRef.current.muted = false;
    setMixerOn(false); setSolo(null); setStemState('idle');
  };

  // Gains implement solo/mute; the video is muted while the mixer is on.
  useEffect(() => {
    if (!mixerOn) return;
    speakers.forEach(spk => {
      const a = stemRef.current[spk];
      if (!a) return;
      const gain = muted[spk] ? 0 : (solo && solo !== spk ? 0 : 1);
      a.volume = Math.max(0, Math.min(1, gain * volume));
    });
  }, [mixerOn, solo, muted, volume, speakers]);

  // Keep the stems glued to the video clock.
  useEffect(() => {
    if (!mixerOn) return;
    const v = videoRef.current;
    if (!v) return;
    const all = () => Object.values(stemRef.current);
    const onPlay = () => all().forEach(a => a.play().catch(() => {}));
    const onPause = () => all().forEach(a => a.pause());
    const onSeek = () => all().forEach(a => { try { a.currentTime = v.currentTime; } catch {} });
    v.addEventListener('play', onPlay);
    v.addEventListener('pause', onPause);
    v.addEventListener('seeked', onSeek);
    let raf = 0;
    const tick = () => {
      if (!v.paused) all().forEach(a => { if (Math.abs(a.currentTime - v.currentTime) > 0.15) { try { a.currentTime = v.currentTime; } catch {} } });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      v.removeEventListener('play', onPlay);
      v.removeEventListener('pause', onPause);
      v.removeEventListener('seeked', onSeek);
      cancelAnimationFrame(raf);
    };
  }, [mixerOn]);

  const videoSrc = timeline
    ? ((videoMode === 'dubbed' && timeline.dubbed_video_url) ? timeline.dubbed_video_url : timeline.source_video_url)
    : '';
  const videoName = videoMode === 'dubbed' ? 'dubbed_video.mp4' : 'source_video.mp4';

  const seekTo = (t) => {
    const c = Math.max(0, Math.min(duration, t));
    setPlayhead(c);
    if (videoRef.current) videoRef.current.currentTime = c;
  };
  const togglePlay = () => {
    const v = videoRef.current; if (!v) return;
    if (v.paused) v.play().catch(() => {}); else v.pause();
  };
  const stopPlayback = () => {
    const v = videoRef.current; if (v) { v.pause(); v.currentTime = 0; }
    setPlayhead(0);
  };
  const stepSegment = (dir) => {
    if (!timeline) return;
    const starts = timeline.segments.map(s => s.start).sort((a, b) => a - b);
    const t = videoRef.current ? videoRef.current.currentTime : playhead;
    if (dir < 0) {
      const prev = [...starts].reverse().find(x => x < t - 0.05);
      seekTo(prev === undefined ? 0 : prev);
    } else {
      const next = starts.find(x => x > t + 0.05);
      seekTo(next === undefined ? duration : next);
    }
  };

  const timeFromEvent = (clientX) => {
    const rail = railRef.current; if (!rail) return 0;
    const rect = rail.getBoundingClientRect();
    return Math.max(0, Math.min(duration, (clientX - rect.left) / pxPerSec));
  };
  const move = (event, idx) => {
    const start = timeFromEvent(event.clientX);
    setTimeline(t => ({ ...t, segments: t.segments.map(s => s.idx === idx ? { ...s, start } : s) }));
  };
  // Drag-to-scrub. Razor keeps cutting; otherwise pointer-drag moves the
  // playhead (ruler, source waveform and speaker lanes are all draggable).
  const scrubDown = (e) => {
    if (tool === 'razor') { addCutAt(timeFromEvent(e.clientX)); return; }
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch {}
    setScrubbing(true);
    seekTo(timeFromEvent(e.clientX));
  };
  const scrubMove = (e) => { if (scrubbing) seekTo(timeFromEvent(e.clientX)); };
  const scrubUp = (e) => {
    if (!scrubbing) return;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
    setScrubbing(false);
  };
  const apply = async () => {
    if (!timeline) return;
    setSaving(true); setError(null);
    const fd = new FormData();
    fd.append('placements', JSON.stringify(timeline.segments.map(s => ({ idx: s.idx, start: s.start }))));
    fd.append('cuts', JSON.stringify(timeline.cuts || []));
    try {
      const r = await fetch(`/api/dub/${job.id}/timeline`, { method: 'POST', body: fd });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || 'Timeline rebuild failed');
      onApplied();
    } catch (e) { setError(e.message); } finally { setSaving(false); }
  };
  // Points where the speaker changes - the cuts a user actually wants. Cuts
  // snap to these when close, so slicing lands on the turn rather than mid-word.
  const changePoints = useMemo(() => {
    if (!timeline) return [];
    const pts = new Set([0]);
    let prev = null;
    for (const s of [...timeline.segments].sort((a, b) => a.start - b.start)) {
      const spk = s.speaker || 'SPEAKER_00';
      if (prev !== null && spk !== prev) pts.add(Number(s.start.toFixed(3)));
      prev = spk;
    }
    return [...pts].sort((a, b) => a - b);
  }, [timeline]);
  const snapTime = (t) => {
    let best = t, bestDist = 0.35;
    for (const p of changePoints) {
      const d = Math.abs(p - t);
      if (d < bestDist) { bestDist = d; best = p; }
    }
    return Number(best.toFixed(3));
  };
  const addCutAt = (t) => setTimeline(x => ({
    ...x, cuts: [...new Set([...(x.cuts || []), snapTime(t)])].sort((a, b) => a - b),
  }));
  const removeCut = (c) => setTimeline(x => ({ ...x, cuts: (x.cuts || []).filter(v => v !== c) }));
  // One click places a cut at EVERY speaker-change point (the razor does one
  // at a time). Union, not replace: manual cuts the user already placed stay.
  const autoCuts = useMemo(
    () => changePoints.filter(p => p > 0 && p < duration),
    [changePoints, duration]
  );
  const sliceAtSpeakerChanges = () => setTimeline(x => ({
    ...x,
    cuts: [...new Set([...(x.cuts || []), ...autoCuts])].sort((a, b) => a - b),
  }));
  const clearCuts = () => setTimeline(x => ({ ...x, cuts: [] }));

  // Per-turn WAV export: slices dubbed_audio.wav at the same boundaries the
  // cut lines show (speaker changes + persisted manual cuts). Files land in
  // the job's turns/ folder with a manifest.json for external editors.
  const [turnExport, setTurnExport] = useState({ loading: false, error: null, files: null });
  const exportTurns = async () => {
    setTurnExport({ loading: true, error: null, files: null });
    try {
      const r = await fetch(`/api/dub/${job.id}/turns/export`, { method: 'POST' });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || 'Turn export failed');
      setTurnExport({ loading: false, error: null, files: d.turns || [], count: d.count });
    } catch (e) {
      setTurnExport({ loading: false, error: e.message, files: null });
    }
  };

  // Per-speaker stem export: ensures every full-length stem is rendered and
  // writes stems_manifest.json (clip positions, both clocks, both texts).
  const [stemExport, setStemExport] = useState({ loading: false, error: null, result: null });
  const exportStems = async () => {
    setStemExport({ loading: true, error: null, result: null });
    try {
      const r = await fetch(`/api/dub/${job.id}/stems/export`, { method: 'POST' });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || 'Stem export failed');
      setStemExport({ loading: false, error: null, result: d });
    } catch (e) {
      setStemExport({ loading: false, error: e.message, result: null });
    }
  };

  if (!timeline) {
    return (
      <div className="mono" style={{ fontSize: 11, color: loadFailed ? 'var(--err)' : 'var(--ink-3)', padding: '10px 0' }}>
        {loadFailed ? (
          <>
            {loadFailed}
            <button className="btn" style={{ marginLeft: 10 }} onClick={() => setReloadKey(k => k + 1)}>Retry</button>
          </>
        ) : 'Loading clips…'}
      </div>
    );
  }

  const RULER_H = 26, WAVE_H = 52, TEXT_H = 30, TR_H = 36, SPK_H = 76;
  const rowStyle = (h) => ({ position: 'relative', height: h, width: totalWidth, borderBottom: '1px solid var(--line)' });
  const headerRow = (h, children) => ({ height: h, borderBottom: '1px solid var(--line)', display: 'flex', alignItems: 'center', padding: '0 10px', minWidth: 0 });

  const transportBtn = (label, onClick, extra) => (
    <button onClick={onClick} title={extra} style={{
      width: 30, height: 26, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      borderRadius: 4, border: '1px solid var(--line)', background: 'var(--bg-2)', color: 'var(--ink-2)',
      cursor: 'pointer',
    }}>{label}</button>
  );

  return (
    <div>
      {/* ── Video + transport ── */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'stretch', marginBottom: 10 }}>
        <div style={{ flex: 1, minWidth: 0, background: '#000', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--line)' }}>
          <video
            ref={videoRef}
            src={videoSrc}
            onTimeUpdate={e => setPlayhead(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onError={() => videoMode === 'dubbed' && setVideoMode('original')}
            style={{ width: '100%', maxHeight: 340, display: 'block', background: '#000' }}
          />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center', marginBottom: 8 }}>
        {transportBtn(ED.toStart, () => seekTo(0), 'Go to start')}
        {transportBtn(ED.prev, () => stepSegment(-1), 'Previous clip')}
        {transportBtn(ED.stop, stopPlayback, 'Stop')}
        <button onClick={togglePlay} title={playing ? 'Pause' : 'Play'} style={{
          width: 44, height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          borderRadius: 4, border: '1px solid var(--accent)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer',
        }}>{playing ? ED.pause : ED.play}</button>
        {transportBtn(ED.next, () => stepSegment(1), 'Next clip')}
        {transportBtn(ED.toEnd, () => seekTo(duration), 'Go to end')}
        <div style={{ width: 14 }}/>
        <button className="btn-ghost" onClick={() => setVideoMode(m => m === 'dubbed' ? 'original' : 'dubbed')}
          style={{ fontSize: 11, color: 'var(--ink-3)', border: '1px solid var(--line)', borderRadius: 4, padding: '4px 8px' }}>
          {videoMode === 'dubbed' ? 'Dubbed' : 'Original'} video
        </button>
      </div>

      {/* ── Tools / zoom / speed / volume ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[['select', ED.pointer, 'Select — drag clips'], ['razor', ED.razor, 'Cut — click a lane to split']].map(([id, ic, hint]) => (
            <button key={id} title={hint} onClick={() => setTool(id)} style={{
              width: 28, height: 24, borderRadius: 4, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid ' + (tool === id ? 'var(--accent)' : 'var(--line)'),
              background: tool === id ? 'var(--accent-dim)' : 'var(--bg-2)',
              color: tool === id ? 'var(--accent)' : 'var(--ink-3)', cursor: 'pointer',
            }}>{ic}</button>
          ))}
        </div>
        <button className="btn-ghost" onClick={() => addCutAt(playhead)} style={{ fontSize: 11, color: 'var(--ink-3)', border: '1px solid var(--line)', borderRadius: 4, padding: '4px 8px' }}>
          Cut at {fmtSec(playhead)}
        </button>
        <button className="btn-ghost" onClick={sliceAtSpeakerChanges} disabled={!autoCuts.length}
          title={`Place a cut at every speaker-change point (${autoCuts.length})`}
          style={{ fontSize: 11, color: autoCuts.length ? 'var(--ink-2)' : 'var(--ink-4)', border: '1px solid var(--line)', borderRadius: 4, padding: '4px 8px', cursor: autoCuts.length ? 'pointer' : 'default' }}>
          Slice at speaker changes{autoCuts.length ? ` (${autoCuts.length})` : ''}
        </button>
        {(timeline.cuts || []).length > 0 && (
          <button className="btn-ghost" onClick={clearCuts}
            title="Remove every cut marker"
            style={{ fontSize: 11, color: 'var(--ink-3)', border: '1px solid var(--line)', borderRadius: 4, padding: '4px 8px' }}>
            Clear cuts
          </button>
        )}
        <span className="mono" style={{ fontSize: 10, color: stemState === 'error' ? 'var(--err)' : 'var(--ink-4)' }}>
          {stemState === 'loading' ? 'preparing stems...'
            : stemState === 'error' ? 'stems unavailable - solo/mute are visual only'
            : mixerOn ? 'stems on'
            : 'S / M enable per-speaker audio'}
        </span>
        {mixerOn && (
          <button className="btn-ghost" onClick={disableMixer} style={{ fontSize: 11, color: 'var(--ink-3)', border: '1px solid var(--line)', borderRadius: 4, padding: '4px 8px' }}>
            Mixer off
          </button>
        )}
        <div style={{ flex: 1 }}/>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="caps">Zoom</span>
          <button className="btn-ghost" onClick={() => setPxPerSec(z => Math.max(6, Math.round(z / 1.5)))} style={{ color: 'var(--ink-3)', padding: 0 }}>−</button>
          <input type="range" min="6" max="220" value={pxPerSec} onChange={e => setPxPerSec(Number(e.target.value))} style={{ width: 90 }}/>
          <button className="btn-ghost" onClick={() => setPxPerSec(z => Math.min(220, Math.round(z * 1.5)))} style={{ color: 'var(--ink-3)', padding: 0 }}>+</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="caps">Speed</span>
          <select value={speed} onChange={e => setSpeed(Number(e.target.value))} style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 4, padding: '3px 6px', fontSize: 11, color: 'var(--ink-2)' }}>
            {[0.5, 0.75, 1, 1.25, 1.5, 2].map(v => <option key={v} value={v}>{v}×</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button className="btn-ghost" title="Mute" onClick={() => setVolume(v => v > 0 ? 0 : 1)} style={{ color: volume > 0 ? 'var(--ink-3)' : 'var(--err)', padding: 0 }}>
            {volume > 0 ? ED.volume : ED.dim}
          </button>
          <input type="range" min="0" max="1" step="0.02" value={volume} onChange={e => setVolume(Number(e.target.value))} style={{ width: 70 }}/>
        </div>
      </div>

      {/* ── Track grid ── */}
      <div style={{ display: 'flex', border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg-1)' }}>
        {/* Header column */}
        <div style={{ width: 208, flexShrink: 0, borderRight: '1px solid var(--line)', background: 'var(--bg-1)' }}>
          <div style={{ ...headerRow(RULER_H), justifyContent: 'flex-start' }}>
            <span className="mono" style={{ fontSize: 17, color: 'var(--ink)', letterSpacing: '-0.02em' }}>{fmtTimecode(playhead)}</span>
          </div>
          <div style={{ ...headerRow(WAVE_H), justifyContent: 'space-between' }}>
            <span style={{ fontSize: 11.5, color: 'var(--ink-4)' }}>Source Speech</span>
            {!timeline.speech_stem && (
              <span className="mono" style={{ fontSize: 9, color: 'var(--ink-4)' }}>full mix</span>
            )}
          </div>
          <div style={{ ...headerRow(WAVE_H), justifyContent: 'space-between' }}>
            <span style={{ fontSize: 11.5, color: 'var(--ink-4)' }}>Background</span>
            {!timeline.bg_peaks?.length && (
              <span className="mono" style={{ fontSize: 9, color: 'var(--ink-4)' }}>no stem</span>
            )}
          </div>
          <div style={{ ...headerRow(TEXT_H), fontSize: 11.5, color: 'var(--ink-3)' }}>Original Text</div>
          <div style={{ ...headerRow(TR_H), fontSize: 11.5, color: 'var(--ink-2)' }}>Translated Text</div>
          {speakers.map(spk => {
            const segs = segsBySpeaker[spk] || [];
            return (
              <div key={spk} style={{ height: SPK_H, borderBottom: '1px solid var(--line)', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 4 }}>
                  <SMBtn active={solo === spk} onClick={() => { enableMixer(); setSolo(solo === spk ? null : spk); }} label="S" title="Solo — highlight this speaker"/>
                  <SMBtn active={!!muted[spk]} onClick={() => { enableMixer(); setMuted(m => ({ ...m, [spk]: !m[spk] })); }} label="M" title="Mute — dim this speaker"/>
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 11.5, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{niceSpeaker(spk)}</div>
                  <div className="mono" style={{ fontSize: 9, color: 'var(--ink-4)' }}>{segs.length} clip{segs.length === 1 ? '' : 's'}</div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Lanes (horizontally scrollable) */}
        <div className="scroll" style={{ flex: 1, overflowX: 'auto', overflowY: 'hidden', minWidth: 0 }}>
          <div ref={railRef} style={{ position: 'relative', width: totalWidth }}>
            {/* Ruler */}
            <div
              onPointerDown={scrubDown}
              onPointerMove={scrubMove}
              onPointerUp={scrubUp}
              style={{ ...rowStyle(RULER_H), background: 'var(--bg-2)', cursor: tool === 'razor' ? 'crosshair' : 'ew-resize', touchAction: 'none' }}
            >
              {ticks.map((t, i) => (
                <div key={i} style={{ position: 'absolute', left: t * pxPerSec, top: 0, bottom: 0, borderLeft: '1px solid var(--line-2)' }}>
                  <span className="mono" style={{ position: 'absolute', left: 4, top: 6, fontSize: 9, color: 'var(--ink-4)', whiteSpace: 'nowrap' }}>{fmtSec(t)}</span>
                </div>
              ))}
            </div>

            {/* Lane 1 — separated source speech: the original language audio
                (NOT translated), so the reference sits directly above the
                translated tracks. Jobs without stems fall back to the full
                mix server-side; speech_stem tells the UI which it is. */}
            <div
              onPointerDown={scrubDown}
              onPointerMove={scrubMove}
              onPointerUp={scrubUp}
              style={{ ...rowStyle(WAVE_H), cursor: tool === 'razor' ? 'crosshair' : 'ew-resize', touchAction: 'none' }}
            >
              <div style={{ position: 'absolute', left: 0, top: 2 }}>
                <WaveformLane peaks={timeline.speech_peaks ?? timeline.source_peaks} duration={duration} pxPerSec={pxPerSec} height={WAVE_H - 8} color="oklch(0.62 0.02 250)"/>
              </div>
            </div>

            {/* Lane 2 — separated background (music/SFX), kept apart from the
                speech so the dub can be judged against the original bed. */}
            <div
              onPointerDown={scrubDown}
              onPointerMove={scrubMove}
              onPointerUp={scrubUp}
              style={{ ...rowStyle(WAVE_H), cursor: tool === 'razor' ? 'crosshair' : 'ew-resize', touchAction: 'none' }}
            >
              <div style={{ position: 'absolute', left: 0, top: 2 }}>
                <WaveformLane peaks={timeline.bg_peaks} duration={duration} pxPerSec={pxPerSec} height={WAVE_H - 8} color="oklch(0.7 0.09 300)"/>
              </div>
              {!timeline.bg_peaks?.length && (
                <div style={{ position: 'absolute', left: 8, top: 19, fontSize: 10, color: 'var(--ink-4)' }}>
                  No separated background for this job
                </div>
              )}
            </div>

            {/* Original Text lane */}
            <div style={rowStyle(TEXT_H)}>
              {timeline.segments.map(s => {
                const a = s.source_start, b = s.source_end;
                const left = a * pxPerSec, w = Math.max(6, (b - a) * pxPerSec - 2);
                return (
                  <div key={'o' + s.idx} title={s.original_text} style={{
                    position: 'absolute', left, width: w, top: 4, height: TEXT_H - 8,
                    background: 'var(--bg-3)', border: '1px solid var(--line-2)', borderRadius: 3,
                    fontSize: 10, color: 'var(--ink-3)', padding: '3px 6px', overflow: 'hidden', whiteSpace: 'nowrap',
                  }}>{s.original_text}</div>
                );
              })}
            </div>

            {/* Translated Text lane (draggable clips) */}
            <div style={rowStyle(TR_H)}>
              {timeline.segments.map(s => {
                const left = s.start * pxPerSec, w = Math.max(10, s.duration * pxPerSec - 2);
                return (
                  <div key={'t' + s.idx} title={s.text}
                    onPointerDown={e => { if (tool === 'razor') { addCutAt(timeFromEvent(e.clientX)); return; } e.currentTarget.setPointerCapture(e.pointerId); setDragging(s.idx); move(e, s.idx); }}
                    onPointerMove={e => dragging === s.idx && move(e, s.idx)}
                    onPointerUp={e => { if (dragging === s.idx) { e.currentTarget.releasePointerCapture(e.pointerId); setDragging(null); } }}
                    style={{
                      position: 'absolute', left, width: w, top: 3, height: TR_H - 6,
                      borderRadius: 4, cursor: tool === 'razor' ? 'crosshair' : 'ew-resize',
                      background: 'var(--accent-dim)', border: '1px solid var(--accent)', color: 'var(--ink)',
                      fontSize: 10, padding: '4px 6px', overflow: 'hidden', whiteSpace: 'nowrap',
                    }}>{s.text}</div>
                );
              })}
            </div>

            {/* Speaker waveform lanes */}
            {speakers.map(spk => {
              const segs = segsBySpeaker[spk] || [];
              const a = segs.length ? Math.min(...segs.map(s => s.start)) : 0;
              const b = segs.length ? Math.max(...segs.map(s => s.start + s.duration)) : 0;
              const activeRanges = JSON.stringify(segs.map(s => [s.start, s.start + s.duration]));
              const dim = !!solo && solo !== spk;
              return (
                <div key={spk}
                  onPointerDown={scrubDown}
                  onPointerMove={scrubMove}
                  onPointerUp={scrubUp}
                  style={{ ...rowStyle(SPK_H), cursor: tool === 'razor' ? 'crosshair' : 'ew-resize', opacity: muted[spk] ? 0.4 : 1, touchAction: 'none' }}
                >
                  <div style={{ position: 'absolute', left: 0, top: 2 }}>
                    <WaveformLane peaks={timeline.peaks} duration={duration} pxPerSec={pxPerSec} height={SPK_H - 8} activeKey={activeRanges} dim={dim}/>
                  </div>
                  {segs.length > 0 && (
                    <div style={{
                      position: 'absolute', left: a * pxPerSec, top: SPK_H - 22, width: Math.max(46, (b - a) * pxPerSec),
                      height: 16, background: 'var(--bg-2)', border: '1px solid var(--line-2)', borderRadius: 3,
                      fontSize: 9, color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 4,
                      padding: '0 5px', overflow: 'hidden', whiteSpace: 'nowrap',
                    }}>{ED.link} {videoName} · {fmtSec(b - a)}</div>
                  )}
                </div>
              );
            })}

            {/* Cuts + playhead overlay */}
            {(timeline.cuts || []).map(c => (
              <div key={'c' + c} onClick={() => removeCut(c)} title={'Cut at ' + fmtSec(c) + ' — click to remove'} style={{
                position: 'absolute', left: c * pxPerSec, top: 0, bottom: 0, width: 2, background: 'var(--warn)', cursor: 'pointer', zIndex: 4,
              }}/>
            ))}
            <div style={{ position: 'absolute', left: playhead * pxPerSec, top: 0, bottom: 0, width: 2, background: 'var(--err)', zIndex: 5, pointerEvents: 'none' }}/>
            <div style={{ position: 'absolute', left: playhead * pxPerSec - 5, top: 0, width: 10, height: 9, background: 'var(--err)', clipPath: 'polygon(0 0, 100% 0, 50% 100%)', zIndex: 6, pointerEvents: 'none' }}/>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10 }}>
        <button className="btn btn-primary" disabled={saving} onClick={apply}>{saving ? 'Rebuilding timing…' : 'Apply timing to video'}</button>
        <button className="btn-ghost" disabled={turnExport.loading} onClick={exportTurns}
          title="Slice dubbed_audio.wav at the shown cut lines → one WAV per turn in turns/"
          style={{ fontSize: 11, color: 'var(--ink-2)', border: '1px solid var(--line)', borderRadius: 4, padding: '5px 9px' }}>
          {turnExport.loading ? 'Slicing…' : 'Export turn WAVs'}
        </button>
        <button className="btn-ghost" disabled={stemExport.loading} onClick={exportStems}
          title="Render every speaker's full-length stem + stems_manifest.json (clip positions, both clocks, both texts)"
          style={{ fontSize: 11, color: 'var(--ink-2)', border: '1px solid var(--line)', borderRadius: 4, padding: '5px 9px' }}>
          {stemExport.loading ? 'Rendering…' : 'Export stems'}
        </button>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
          {(() => {
            const cs = timeline.cuts || [];
            if (!cs.length) return 'Cuts: none';
            return cs.length <= 6
              ? `Cuts: ${cs.map(c => fmtSec(c)).join(', ')}`
              : `Cuts: ${cs.length} (${cs.slice(0, 3).map(c => fmtSec(c)).join(', ')}, …)`;
          })()}
        </span>
        <div style={{ flex: 1 }}/>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{timeline.segments.length} segments · {speakers.length} speakers</span>
      </div>
      {turnExport.files && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <span style={{ color: 'var(--accent)' }}>{turnExport.count} turn WAVs → turns/</span>
          {turnExport.files.slice(0, 8).map(t => (
            <a key={t.file} href={t.url} download style={{ color: 'var(--ink-2)', textDecoration: 'underline' }}>
              {fmtSec(t.start)} {niceSpeaker(t.speaker)}
            </a>
          ))}
          {turnExport.files.length > 8 && <span>+{turnExport.files.length - 8} more</span>}
        </div>
      )}
      {turnExport.error && <div style={{ color: 'var(--err)', fontSize: 11, marginTop: 8 }}>{turnExport.error}</div>}
      {stemExport.result && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <span style={{ color: 'var(--accent)' }}>
            {stemExport.result.count} stems + manifest → job folder
          </span>
          {stemExport.result.stems.map(s => (
            <a key={s.speaker} href={s.url} download style={{ color: 'var(--ink-2)', textDecoration: 'underline' }}>
              {niceSpeaker(s.speaker)}
            </a>
          ))}
          <a href={stemExport.result.manifest_url} download style={{ color: 'var(--ink-4)', textDecoration: 'underline' }}>
            manifest.json
          </a>
        </div>
      )}
      {stemExport.error && <div style={{ color: 'var(--err)', fontSize: 11, marginTop: 8 }}>{stemExport.error}</div>}
      {error && <div style={{ color: 'var(--err)', fontSize: 11, marginTop: 10 }}>{error}</div>}
    </div>
  );
}

// ── Expandable panel chrome ─────────────────────────────────────────
