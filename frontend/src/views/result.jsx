// Result view — completed dub player + export
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useMemo } = React;
import { fmtAge, fmtSec } from '../constants';
import { I } from '../icons';
import { Select } from '../ui';
import { ExpandPanel, ExportPanel, LipSyncPanel, RegenPanel, SubsPanel } from './panels';

// ═══════════════════════════════════════════════════════════════════
// RESULT VIEW — completed dub. Export hero (preset cards), video, panels.
// Real wiring:
//   - Player srces /outputs/{id}/dubbed_video.mp4
//   - Burn subs panel preview/render hits subs_preview / burn_subs
//   - Lip-sync panel hits /api/lip_sync/status + /api/dub/{id}/lip_sync
//   - Regenerate panel hits /api/dub/{id}/retry_tts
//   - Export-for-platform: hits /api/dub/{id}/export with preset form param
// ═══════════════════════════════════════════════════════════════════
export function ResultView({ jobs, selectedJobId, voicePresets, onPickJob, onSwitchToHome, onSwitchToHistory }) {
  // Pick the job: explicit selection > most recent complete
  const completedJobs = useMemo(
    () => jobs.filter(j => j.status === 'complete').sort((a, b) => (b.completed_at || b.created || 0) - (a.completed_at || a.created || 0)),
    [jobs]
  );
  const job = useMemo(() => {
    if (selectedJobId) return jobs.find(j => j.id === selectedJobId);
    return completedJobs[0];
  }, [jobs, selectedJobId, completedJobs]);

  // Empty state
  if (!job) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, padding: 40, background: 'var(--bg)' }}>
        <div className="caps">No completed jobs yet</div>
        <div className="serif" style={{ fontSize: 32, letterSpacing: '-0.015em', textAlign: 'center', maxWidth: 480 }}>
          Nothing to <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>show off</span> yet.
        </div>
        <div style={{ fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 360, lineHeight: 1.5 }}>
          When a dub finishes, this view shows the video, downloads, export presets, and per-segment controls.
        </div>
        <button onClick={onSwitchToHome} className="btn btn-primary" style={{ marginTop: 8 }}>
          {I.arrow} Start your first dub
        </button>
      </div>
    );
  }

  return <ResultViewInner job={job} jobs={completedJobs} voicePresets={voicePresets} onPickJob={onPickJob} onSwitchToHistory={onSwitchToHistory}/>;
}

export function ResultViewInner({ job, jobs, voicePresets, onPickJob, onSwitchToHistory }) {
  // Cache-bust the video URL so an updated dub (after regenerate / lip-sync /
  // burn subs) reflects immediately instead of showing a stale browser cache.
  const [videoVersion, setVideoVersion] = useState(0);
  const [videoOverrideUrl, setVideoOverrideUrl] = useState(null); // for lip-sync / burn-subs swap

  const videoUrl = useMemo(() => {
    const base = videoOverrideUrl || `/outputs/${job.id}/dubbed_video.mp4`;
    const sep = base.includes('?') ? '&' : '?';
    return base + sep + 'v=' + videoVersion + '_' + (job.completed_at || 0);
  }, [job.id, job.completed_at, videoOverrideUrl, videoVersion]);

  // Panel open/close
  const [open, setOpen] = useState({ export: false, subs: false, lipsync: false, regen: false });
  const toggle = (k) => setOpen(o => ({ ...o, [k]: !o[k] }));

  return (
    <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '36px 36px 80px' }}>

        {/* Hero — title, meta, job switcher */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 24, marginBottom: 28 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="caps" style={{ marginBottom: 8 }}>
              <span style={{ color: 'var(--accent)' }}>● Completed</span>
              <span style={{ marginLeft: 10, color: 'var(--ink-4)' }}>
                {job.id?.slice(0, 8)} · {fmtAge(job.completed_at || job.created)}
              </span>
            </div>
            <div className="serif" style={{ fontSize: 32, lineHeight: 1.05, letterSpacing: '-0.015em', marginBottom: 10 }}>
              {job.source_label || job.source || job.id}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-3)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {job.target_lang && <span>→ {job.target_lang}</span>}
              {job.duration && <><span style={{ color: 'var(--ink-4)' }}>·</span><span className="mono">{fmtSec(job.duration)}</span></>}
              {job.model && <><span style={{ color: 'var(--ink-4)' }}>·</span><span className="mono">{job.model}</span></>}
              {job.speaker_mode && <><span style={{ color: 'var(--ink-4)' }}>·</span><span>{job.speaker_mode === 'main' ? 'main speaker' : 'all speakers'}</span></>}
            </div>
          </div>

          {/* Switcher: pick another completed job */}
          {jobs.length > 1 && (
            <div style={{ flexShrink: 0 }}>
              <Select value={job.id} onChange={onPickJob}>
                {jobs.slice(0, 20).map(j => (
                  <option key={j.id} value={j.id} style={{ background: '#16161c' }}>
                    {(j.source_label || j.source || j.id).slice(0, 50)}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>

        {/* ─────────────────────────────────────────────────── */}
        {/* EXPORT FOR PLATFORM — preset cards FIRST per scoping */}
        {/* ─────────────────────────────────────────────────── */}
        <ExportPanel job={job}/>

        {/* ─────────────────────────────────────────────────── */}
        {/* VIDEO PLAYER + downloads                              */}
        {/* ─────────────────────────────────────────────────── */}
        <div style={{ marginTop: 32, marginBottom: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div className="caps">Dubbed video</div>
            <div style={{ flex: 1 }}/>
            <a href={videoUrl} download={`dubbed_${job.id?.slice(0, 8)}.mp4`} className="btn">
              {I.arrow} Download MP4
            </a>
          </div>
          <div style={{
            background: '#000', border: '1px solid var(--line)', borderRadius: 8,
            overflow: 'hidden', position: 'relative',
          }}>
            <video src={videoUrl} controls style={{ width: '100%', maxHeight: '56vh', display: 'block' }}/>
          </div>
        </div>

        {/* Asset downloads row */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 32, flexWrap: 'wrap' }}>
          <a className="btn" href={`/outputs/${job.id}/translated.srt`} download>
            {I.arrow} .srt subtitles
          </a>
          <a className="btn" href={`/api/dub/${job.id}/transcripts.txt`}>
            {I.arrow} .txt transcript
          </a>
          <div style={{ flex: 1 }}/>
          <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', alignSelf: 'center' }}>
            files in ~/tachidubb/output/{job.id?.slice(0, 8)}/
          </span>
        </div>

        {/* ─────────────────────────────────────────────────── */}
        {/* POST-PROCESSING PANELS                                */}
        {/* ─────────────────────────────────────────────────── */}
        <div className="caps" style={{ marginBottom: 12 }}>Post-processing</div>

        <ExpandPanel
          open={open.subs} onToggle={() => toggle('subs')}
          title="Burn subtitles into video"
          subtitle="Hard-code subs at chosen style. Preview a frame first (~2s)."
          icon={<span style={{ fontSize: 13 }}>Aa</span>}
        >
          <SubsPanel job={job} onBurned={(url) => { setVideoOverrideUrl(url); setVideoVersion(v => v + 1); }}/>
        </ExpandPanel>

        <ExpandPanel
          open={open.lipsync} onToggle={() => toggle('lipsync')}
          title="Lip-sync (MuseTalk)"
          subtitle="Match speaker mouth movement to dubbed audio. Optional — only useful for talking-head footage."
          icon={<span style={{ fontSize: 13 }}>◑</span>}
        >
          <LipSyncPanel job={job} onSynced={(url) => { setVideoOverrideUrl(url); setVideoVersion(v => v + 1); }}/>
        </ExpandPanel>

        <ExpandPanel
          open={open.regen} onToggle={() => toggle('regen')}
          title="Regenerate with different voice"
          subtitle="Keeps transcript & translation. Re-runs TTS only."
          icon={<span style={{ fontSize: 13 }}>↻</span>}
        >
          <RegenPanel job={job} voicePresets={voicePresets} onSubmitted={onSwitchToHistory}/>
        </ExpandPanel>

      </div>
    </div>
  );
}

