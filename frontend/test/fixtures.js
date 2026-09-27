// Realistic fixtures for UI tests.
// Shapes mirror what the backend actually serves (see app/routers/*).

export const systemFixture = {
  ready: true,
  gpu: { ok: true, name: 'GeForce RTX 5070', vram_gb: 12, vram_free_gb: 8.3 },
  ollama: { ok: true, models: ['aya-expanse:8b', 'qwen2.5:7b'] },
  python: { ok: true, version: '3.11.16' },
  ffmpeg: { ok: true, version: '6.1' },
  whisper: { ok: true },
  voxcpm: { ok: true },
  yt_dlp: { ok: true },
  edge_tts: { ok: true },
  pyannote: { ok: false },
};

export const voicePresetFixture = {
  id: 'vp-1',
  type: 'file',
  name: 'French Narrator',
  description: 'Calm female reference',
  language: 'fr',
  gender: 'female',
  audio_url: '/api/voice_presets/vp-1/audio',
  file_ext: 'wav',
  file_size: 512000,
};

/** A completed job; pass overrides to derive error/active variants. */
export function makeJob(overrides = {}) {
  return {
    id: 'job-1',
    status: 'complete',
    source: 'demo.mp4',
    source_label: 'demo.mp4',
    created: 1756000000,
    completed_at: 1756000600,
    target_lang: 'fr',
    source_lang: 'en',
    model: 'aya-expanse:8b',
    whisper_model: 'large-v3',
    progress: 100,
    duration: 120,
    starred: false,
    batch_label: '',
    error: '',
    transcript: [],
    tts_speed: 'balanced',
    voice_preset: 'auto',
    ...overrides,
  };
}
