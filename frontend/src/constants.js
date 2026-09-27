// Shared constants + format helpers
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build

// ═══════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════

export const LANGS = [
  { c: 'auto', n: 'Auto-detect' },
  { c: 'en', n: 'English' },
  { c: 'ru', n: 'Russian' },
  { c: 'es', n: 'Spanish' },
  { c: 'pt', n: 'Portuguese' },
  { c: 'fr', n: 'French' },
  { c: 'de', n: 'German' },
  { c: 'it', n: 'Italian' },
  { c: 'pl', n: 'Polish' },
  { c: 'tr', n: 'Turkish' },
  { c: 'ja', n: 'Japanese' },
  { c: 'ko', n: 'Korean' },
  { c: 'zh', n: 'Chinese (Mandarin)' },
  { c: 'ar', n: 'Arabic' },
  { c: 'hi', n: 'Hindi' },
  { c: 'nl', n: 'Dutch' },
];

export const WHISPER_MODELS = [
  { id: 'large-v3', name: 'large-v3', size: '2.9 GB', detail: 'Best accuracy · slow' },
  { id: 'medium', name: 'medium', size: '1.4 GB', detail: 'Balanced · ~2× faster' },
  { id: 'small', name: 'small', size: '460 MB', detail: 'Fast · clean audio only' },
];

// Active job status set (any of these = job is running on the server)
export const ACTIVE_STATUSES = new Set([
  'queued', 'running', 'downloading', 'extracting', 'resuming',
  'transcribing', 'diarizing', 'translating', 'synthesizing',
  'assembling', 'merging',
]);

// 6-stage pipeline (Tachi mockup uses 6, our backend has more granular states
// but most map naturally onto these). Used by Processing view's stage chain.
export const STAGES = [
  { id: 'import',     label: 'Import',     hint: 'Acquire & prep media' },
  { id: 'analyze',    label: 'Analyze',    hint: 'Transcribe & diarize' },
  { id: 'translate',  label: 'Translate',  hint: 'Render copy' },
  { id: 'review',     label: 'Review',     hint: 'Wizard pause' },
  { id: 'synthesize', label: 'Synthesize', hint: 'Render voices' },
  { id: 'master',     label: 'Master',     hint: 'Mix & merge' },
];

// Server status → which stage is currently active (returns index 0-5).
// Returns -1 if status doesn't map to a stage (idle/done/error).
export const stageForStatus = (status) => {
  switch (status) {
    case 'queued': case 'scheduled': case 'downloading': case 'extracting': case 'resuming':
      return 0;
    case 'transcribing': case 'diarizing': case 'awaiting_transcript_review':
      return 1;
    case 'translating':
      return 2;
    case 'awaiting_translation_review':
      return 3;
    case 'synthesizing':
      return 4;
    case 'assembling': case 'merging':
      return 5;
    case 'complete':
      return 6;
    default:
      return -1;
  }
};

// Map server status → unified UI status meta
export const STATUS_META = {
  complete:                       { color: 'var(--accent)', label: 'Completed' },
  awaiting_translation_review:    { color: 'var(--warn)',   label: 'Awaiting review' },
  error:                          { color: 'var(--err)',    label: 'Error' },
  cancelled:                      { color: 'var(--ink-4)',  label: 'Cancelled' },
  queued:                         { color: 'var(--ink-3)',  label: 'Queued' },
  scheduled:                      { color: '#8a9aff',       label: 'Scheduled' },
  awaiting_transcript_review:     { color: 'var(--warn)',   label: 'Awaiting transcript review' },
  // Active states all show Running
  running:                        { color: 'var(--accent)', label: 'Running' },
  downloading:                    { color: 'var(--accent)', label: 'Downloading' },
  extracting:                     { color: 'var(--accent)', label: 'Extracting' },
  resuming:                       { color: 'var(--accent)', label: 'Resuming' },
  transcribing:                   { color: 'var(--accent)', label: 'Transcribing' },
  diarizing:                      { color: 'var(--accent)', label: 'Diarizing' },
  translating:                    { color: 'var(--accent)', label: 'Translating' },
  synthesizing:                   { color: 'var(--accent)', label: 'Synthesizing' },
  assembling:                     { color: 'var(--accent)', label: 'Assembling' },
  merging:                        { color: 'var(--accent)', label: 'Merging' },
};

// Format helpers
export const fmtSec = (s) => {
  if (!s && s !== 0) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2,'0')}:${sec.toString().padStart(2,'0')}`;
  return `${m.toString().padStart(2,'0')}:${sec.toString().padStart(2,'0')}`;
};

// Relative-time formatter, "2h ago" / "3d ago" / "just now". Server gives
// `created` as a unix-seconds timestamp.
export const fmtAge = (ts) => {
  if (!ts) return '';
  const now = Date.now() / 1000;
  const d = now - ts;
  if (d < 60) return 'just now';
  if (d < 3600) return Math.floor(d / 60) + 'm ago';
  if (d < 86400) return Math.floor(d / 3600) + 'h ago';
  if (d < 7 * 86400) return Math.floor(d / 86400) + 'd ago';
  const dt = new Date(ts * 1000);
  return dt.toLocaleDateString();
};

// localStorage helpers (preserved from current app — same key prefix
// so users don't lose their saved preferences on upgrade)
export const _lsGet = (key, fallback) => {
  try {
    const v = localStorage.getItem('tachidubb_pref_' + key);
    if (v === null) return fallback;
    if (v === 'true') return true;
    if (v === 'false') return false;
    return v;
  } catch (_) { return fallback; }
};
export const _lsSet = (key, v) => {
  try { localStorage.setItem('tachidubb_pref_' + key, String(v)); } catch (_) {}
};

