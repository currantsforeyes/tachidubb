// Review view — wizard pause: speakers + segment edits
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect, useRef, useMemo } = React;
import { fmtSec } from '../constants';
import { I } from '../icons';
import { Select } from '../ui';

// ═══════════════════════════════════════════════════════════════════
// REVIEW VIEW — wizard pause. Speakers left + segments right.
// Loads checkpoint when job is selected. Edits go through
// /api/dub/{id}/edit_translations. Speaker ref replace goes through
// /api/dub/{id}/edit_speaker_ref/{spk}. Continue calls /continue.
// ═══════════════════════════════════════════════════════════════════
export function ReviewView({ jobs, selectedJobId, voicePresets, onContinued, onCancel, onPickJob }) {
  const reviewJobs = useMemo(
    () => jobs.filter(j => j.status === 'awaiting_translation_review' || j.status === 'awaiting_transcript_review'),
    [jobs]
  );

  // Auto-pick first review job if no explicit pick
  const job = useMemo(() => {
    if (selectedJobId) return jobs.find(j => j.id === selectedJobId);
    return reviewJobs[0];
  }, [jobs, selectedJobId, reviewJobs]);

  if (!job) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, padding: 40, background: 'var(--bg)' }}>
        <div className="caps">No reviews pending</div>
        <div className="serif" style={{ fontSize: 32, letterSpacing: '-0.015em', textAlign: 'center', maxWidth: 480 }}>
          Wizard mode is <span style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>quiet</span>.
        </div>
        <div style={{ fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 380, lineHeight: 1.5 }}>
          When a job is run with wizard mode on, it pauses after translation so you can edit segments and replace voice references before TTS starts.
        </div>
      </div>
    );
  }

  return <ReviewViewInner job={job} reviewJobs={reviewJobs} voicePresets={voicePresets} onContinued={onContinued} onCancel={onCancel} onPickJob={onPickJob}/>;
}

export function ReviewViewInner({ job, reviewJobs, voicePresets, onContinued, onCancel, onPickJob }) {
  const [checkpoint, setCheckpoint] = useState(null);
  const [speakers, setSpeakers] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [edits, setEdits] = useState({});  // { idx: newText }
  const [filter, setFilter] = useState('all');  // all | edited
  const [speakerFilter, setSpeakerFilter] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [continuing, setContinuing] = useState(false);

  // Load checkpoint + speakers when job changes
  useEffect(() => {
    setCheckpoint(null); setSpeakers([]); setLoadError(null); setEdits({}); setSelectedIdx(null);
    const stage = job.status === 'awaiting_translation_review' ? 'translation_done' : 'transcription_done';
    fetch(`/api/dub/${job.id}/checkpoint/${stage}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) setLoadError(d.error);
        else setCheckpoint(d);
      })
      .catch(e => setLoadError(String(e)));
    fetch(`/api/job/${job.id}/speakers`)
      .then(r => r.json())
      .then(d => setSpeakers(d.speakers || []))
      .catch(() => {});
  }, [job.id, job.status]);

  const continueJob = async () => {
    setContinuing(true);
    try {
      // Save edits if any
      if (Object.keys(edits).length > 0) {
        const fd = new FormData();
        fd.append('edits', JSON.stringify(edits));
        await fetch(`/api/dub/${job.id}/edit_translations`, { method: 'POST', body: fd });
      }
      // Continue pipeline
      const fd2 = new FormData();
      const r = await fetch(`/api/dub/${job.id}/continue`, { method: 'POST', body: fd2 });
      if (r.ok) onContinued();
      else alert('Continue failed');
    } finally { setContinuing(false); }
  };

  const cancelJob = async () => {
    if (!confirm('Discard this job?')) return;
    await fetch(`/api/dub/${job.id}/cancel`, { method: 'POST' });
    onCancel();
  };

  const segments = checkpoint?.segments || [];
  const editedCount = Object.keys(edits).length;

  // Filter segments
  const filteredSegs = useMemo(() => {
    let arr = segments;
    if (speakerFilter) arr = arr.filter(s => (s.speaker || 'SPEAKER_00') === speakerFilter);
    if (filter === 'edited') arr = arr.filter(s => edits[s.idx] !== undefined);
    return arr;
  }, [segments, filter, speakerFilter, edits]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* Banner */}
      <div style={{
        padding: '14px 36px',
        background: 'oklch(0.78 0.15 60 / 0.06)',
        borderBottom: '1px solid var(--line)',
        display: 'flex', alignItems: 'center', gap: 14, flexShrink: 0,
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: 'oklch(0.78 0.15 60 / 0.14)', border: '1px solid oklch(0.78 0.15 60 / 0.3)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--warn)',
        }}>{I.review}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: 'var(--ink)', fontWeight: 500 }}>
            Pipeline paused — wizard mode.
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {job.source_label || job.source || job.id} · {segments.length} segments to review
          </div>
        </div>
        {reviewJobs.length > 1 && (
          <Select value={job.id} onChange={onPickJob}>
            {reviewJobs.map(j => <option key={j.id} value={j.id} style={{ background: '#16161c' }}>{(j.source_label || j.source || j.id).slice(0, 60)}</option>)}
          </Select>
        )}
        {editedCount > 0 && <span className="chip" style={{ background: 'var(--bg-2)', color: 'var(--ink-2)' }}>{editedCount} edit{editedCount === 1 ? '' : 's'}</span>}
        <button onClick={cancelJob} className="btn">{I.cancel} Discard</button>
        <button onClick={continueJob} disabled={continuing} className="btn btn-primary">
          {I.check} {continuing ? 'Continuing…' : 'Approve & continue'}
        </button>
      </div>

      {loadError && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--err)', fontSize: 12 }}>
          Couldn't load checkpoint: {loadError}
        </div>
      )}

      {!loadError && !checkpoint && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-3)', fontSize: 12 }}>
          Loading checkpoint…
        </div>
      )}

      {checkpoint && (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* LEFT — speakers (40%) */}
          <div style={{ width: '40%', minWidth: 320, borderRight: '1px solid var(--line)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ padding: '20px 24px 12px' }}>
              <div className="caps" style={{ marginBottom: 6 }}>Speakers</div>
              <div className="serif" style={{ fontSize: 20, lineHeight: 1.15, letterSpacing: '-0.01em' }}>
                Check each voice <span style={{ color: 'var(--ink-3)', fontStyle: 'italic' }}>before they clone it</span>.
              </div>
            </div>
            <div className="scroll" style={{ flex: 1, padding: '4px 18px 24px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button onClick={() => setSpeakerFilter(null)} style={{
                padding: '8px 12px', fontSize: 11, textAlign: 'left',
                background: !speakerFilter ? 'var(--bg-2)' : 'transparent',
                border: '1px solid ' + (!speakerFilter ? 'var(--line-2)' : 'transparent'),
                color: !speakerFilter ? 'var(--ink)' : 'var(--ink-3)',
                borderRadius: 6, cursor: 'pointer',
              }}>
                <span className="caps">All speakers · {segments.length} segments</span>
              </button>
              {speakers.length === 0 && (
                <div style={{ padding: 14, fontSize: 11.5, color: 'var(--ink-4)', fontStyle: 'italic' }}>
                  No speaker references found for this job.
                </div>
              )}
              {speakers.map(sp => (
                <SpeakerCard
                  key={sp.speaker}
                  sp={sp}
                  jobId={job.id}
                  selected={speakerFilter === sp.speaker}
                  segCount={segments.filter(s => (s.speaker || 'SPEAKER_00') === sp.speaker).length}
                  onClick={() => setSpeakerFilter(speakerFilter === sp.speaker ? null : sp.speaker)}
                  onReplaced={() => fetch(`/api/job/${job.id}/speakers`).then(r => r.json()).then(d => setSpeakers(d.speakers || []))}
                />
              ))}
            </div>
          </div>

          {/* RIGHT — segments (60%) */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
            <div style={{ padding: '20px 28px 4px' }}>
              <div className="caps" style={{ marginBottom: 6 }}>Translations</div>
              <div className="serif" style={{ fontSize: 20, lineHeight: 1.15 }}>
                Read every line <span style={{ color: 'var(--ink-3)', fontStyle: 'italic' }}>before voices commit</span>.
              </div>
            </div>
            <div style={{ padding: '8px 28px 0', display: 'flex', gap: 20, borderBottom: '1px solid var(--line)' }}>
              <div className={'tab' + (filter === 'all' ? ' active' : '')} onClick={() => setFilter('all')}>
                All · {filteredSegs.length}
              </div>
              <div className={'tab' + (filter === 'edited' ? ' active' : '')} onClick={() => setFilter('edited')}>
                Edited · {editedCount}
              </div>
            </div>
            <div className="scroll" style={{ flex: 1, padding: '10px 24px 28px', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {filteredSegs.length === 0 ? (
                <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--ink-3)', fontSize: 12 }}>
                  No segments match.
                </div>
              ) : filteredSegs.map(seg => (
                <SegmentRow
                  key={seg.idx}
                  seg={seg}
                  selected={selectedIdx === seg.idx}
                  onSelect={() => setSelectedIdx(selectedIdx === seg.idx ? null : seg.idx)}
                  editedValue={edits[seg.idx]}
                  onEdit={v => setEdits({ ...edits, [seg.idx]: v })}
                  onRevert={() => { const c = { ...edits }; delete c[seg.idx]; setEdits(c); }}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Pastel palette for speakers — cycles deterministically through 6 colors
// keyed off the speaker number (so SPEAKER_00 always gets the same color).
export function speakerColor(spkId) {
  const palette = ['#8ad5d5', '#d8a0d8', '#d4cf8a', '#d9a58a', '#a0c0d8', '#bcd5b3'];
  const m = String(spkId).match(/(\d+)$/);
  const i = m ? parseInt(m[1], 10) % palette.length : 0;
  return palette[i];
}

export function SpeakerCard({ sp, jobId, selected, segCount, onClick, onReplaced }) {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef(null);
  const inputRef = useRef(null);
  const isShort = sp.duration_sec < 10;
  const color = speakerColor(sp.speaker);

  const play = (e) => {
    e.stopPropagation();
    if (!audioRef.current) {
      audioRef.current = new Audio(sp.audio_url);
      audioRef.current.onended = () => setPlaying(false);
    }
    if (playing) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setPlaying(false);
    } else {
      audioRef.current.play().then(() => setPlaying(true)).catch(() => {});
    }
  };

  const replace = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append('reference', file);
    await fetch(`/api/dub/${jobId}/edit_speaker_ref/${sp.speaker}`, { method: 'POST', body: fd });
    onReplaced();
  };

  return (
    <div onClick={onClick} style={{
      padding: 14,
      background: selected ? 'var(--bg-2)' : 'var(--bg-1)',
      border: '1px solid ' + (selected ? 'var(--accent-dim)' : isShort ? 'oklch(0.78 0.15 60 / 0.3)' : 'var(--line)'),
      borderRadius: 8, cursor: 'pointer',
      boxShadow: selected ? 'inset 0 0 0 1px var(--accent-dim)' : 'none',
      transition: 'all 0.12s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 6,
          background: color + '1f', border: '1px solid ' + color + '55',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: color, fontSize: 10, fontWeight: 700,
          fontFamily: 'var(--mono)', flexShrink: 0,
        }}>{sp.speaker.replace('SPEAKER_', '').slice(0, 3)}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>{sp.speaker}</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>
            {segCount} segments · ref {sp.duration_sec?.toFixed(1)}s
          </div>
        </div>
        {isShort && <span title="Short reference — clone may degrade" style={{ color: 'var(--warn)' }}>{I.warn}</span>}
      </div>

      <div onClick={e => e.stopPropagation()} style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '8px 10px', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 6,
      }}>
        <button onClick={play} style={{
          width: 24, height: 24, borderRadius: 4,
          background: color, color: '#0a0a0d',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }} title={playing ? 'Stop' : 'Play'}>
          {playing
            ? <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><rect x="2" y="2" width="2.5" height="6"/><rect x="5.5" y="2" width="2.5" height="6"/></svg>
            : <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M2 2v6l5-3z"/></svg>}
        </button>
        <img src={sp.waveform_url} alt="" style={{ flex: 1, height: 22, objectFit: 'cover', opacity: 0.85 }}
          onError={e => { e.target.style.display = 'none'; }}/>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)', flexShrink: 0 }}>
          {sp.duration_sec?.toFixed(1)}s
        </span>
      </div>

      <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 6, marginTop: 10 }}>
        <input ref={inputRef} type="file" accept="audio/*" style={{ display: 'none' }}
          onChange={e => replace(e.target.files[0])}/>
        <button onClick={() => inputRef.current?.click()} className="btn" style={{ flex: 1, justifyContent: 'center' }}>
          {I.upload} Replace reference
        </button>
      </div>
    </div>
  );
}

export function SegmentRow({ seg, selected, onSelect, editedValue, onEdit, onRevert }) {
  const isEdited = editedValue !== undefined;
  const shown = isEdited ? editedValue : (seg.translated_text || '');
  const color = speakerColor(seg.speaker || 'SPEAKER_00');

  return (
    <div onClick={onSelect} style={{
      padding: '11px 14px',
      background: selected ? 'var(--bg-2)' : 'transparent',
      border: '1px solid ' + (selected ? 'var(--accent-dim)' : 'transparent'),
      borderRadius: 6, cursor: 'pointer',
      transition: 'all 0.12s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span className="dot" style={{ background: color }}/>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-2)' }}>{seg.speaker || 'SPEAKER_00'}</span>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
          {fmtSec(seg.start)} · {(seg.end - seg.start).toFixed(1)}s
        </span>
        <div style={{ flex: 1 }}/>
        {isEdited && (
          <span className="mono" style={{ fontSize: 9, color: 'var(--accent)', padding: '1px 5px', border: '1px solid var(--accent)', borderRadius: 3 }}>
            EDITED
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 6, lineHeight: 1.5, fontStyle: 'italic' }}>
        {seg.text}
      </div>
      {selected ? (
        <div onClick={e => e.stopPropagation()}>
          <textarea value={shown} onChange={e => onEdit(e.target.value)} className="field"
            style={{ resize: 'vertical', minHeight: 56, fontSize: 13, lineHeight: 1.5, fontFamily: 'var(--sans)' }}/>
          {isEdited && (
            <div style={{ display: 'flex', gap: 6, marginTop: 6, justifyContent: 'flex-end' }}>
              <button onClick={onRevert} className="btn" style={{ padding: '4px 8px', fontSize: 10 }}>
                {I.refresh} Revert
              </button>
            </div>
          )}
        </div>
      ) : (
        <div style={{ fontSize: 13, color: 'var(--ink)', lineHeight: 1.5 }}>{shown || <span style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}>(no translation)</span>}</div>
      )}
    </div>
  );
}

