// Behavior: the editor's "Export stems" action — POSTs to /stems/export
// and renders the resulting per-speaker download links + manifest.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { TimelinePanel } from '../src/views/editor';
import { fetchCalls, setRoute } from './api.js';

const JOB = 'stemjob';

beforeAll(() => {
  // jsdom has no canvas: give WaveformLane the no-op 2d context it needs.
  HTMLCanvasElement.prototype.getContext = () => ({
    setTransform() {}, clearRect() {}, fillRect() {},
    globalAlpha: 1, fillStyle: '',
  });
});

const timelineFixture = {
  duration: 4.0,
  cuts: [],
  peaks: [0.4, 0.6],
  source_peaks: [0.3, 0.5],
  source_video_url: `/outputs/${JOB}/source_video.mp4`,
  dubbed_video_url: `/outputs/${JOB}/dubbed_video.mp4`,
  source_audio_url: `/outputs/${JOB}/audio_16k.wav`,
  dubbed_audio_url: `/outputs/${JOB}/dubbed_audio.wav`,
  segments: [
    { idx: 0, text: 'Hello', original_text: 'Hola', speaker: 'SPEAKER_00',
      start: 0.0, source_start: 0.0, source_end: 1.4, duration: 1.4 },
    { idx: 1, text: 'Bye', original_text: 'Adios', speaker: 'SPEAKER_01',
      start: 2.0, source_start: 2.0, source_end: 3.4, duration: 1.4 },
  ],
};

describe('export stems', () => {
  it('posts to /stems/export and links each speaker + the manifest', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`, timelineFixture);
    setRoute('POST', `/api/dub/${JOB}/stems/export`, {
      ok: true, count: 2,
      manifest_url: `/outputs/${JOB}/stems_manifest.json`,
      stems: [
        { speaker: 'SPEAKER_00', file: 'stem_SPEAKER_00.wav',
          url: `/api/dub/${JOB}/stem/SPEAKER_00/audio` },
        { speaker: 'SPEAKER_01', file: 'stem_SPEAKER_01.wav',
          url: `/api/dub/${JOB}/stem/SPEAKER_01/audio` },
      ],
    });
    render(<TimelinePanel job={{ id: JOB }} onApplied={vi.fn()} />);

    const btn = await screen.findByRole('button', { name: 'Export stems' });
    fireEvent.click(btn);

    await waitFor(() => expect(
      screen.getByText(/2 stems \+ manifest/),
    ).toBeTruthy());

    const call = fetchCalls.find(c => c.method === 'POST'
      && c.url === `/api/dub/${JOB}/stems/export`);
    expect(call, 'POST /stems/export was never called').toBeTruthy();

    const s0 = screen.getByRole('link', { name: 'Speaker 1' });
    expect(s0.getAttribute('href')).toBe(`/api/dub/${JOB}/stem/SPEAKER_00/audio`);
    const manifest = screen.getByRole('link', { name: 'manifest.json' });
    expect(manifest.getAttribute('href')).toBe(`/outputs/${JOB}/stems_manifest.json`);
  });

  it('shows the server error instead of claiming success', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`, timelineFixture);
    setRoute('POST', `/api/dub/${JOB}/stems/export`,
      { error: 'No rendered segments to export' });
    render(<TimelinePanel job={{ id: JOB }} onApplied={vi.fn()} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Export stems' }));

    await waitFor(() => expect(
      screen.getByText(/No rendered segments to export/),
    ).toBeTruthy());
    expect(screen.queryByText(/stems \+ manifest/)).toBeNull();
  });
});
