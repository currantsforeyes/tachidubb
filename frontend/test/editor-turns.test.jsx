// Behavior: the editor's speaker-turn tools.
//   1. "Slice at speaker changes" places a cut at every change point in one
//      click (the razor only does one at a time) and never drops manual cuts.
//   2. "Export turn WAVs" posts to /turns/export and renders the resulting
//      download links.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { TimelinePanel } from '../src/views/editor';
import { fetchCalls, setRoute } from './api.js';

const JOB = 'turnjob';

// jsdom has no canvas: give WaveformLane the no-op 2d context it needs.
beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = () => ({
    setTransform() {}, clearRect() {}, fillRect() {},
    globalAlpha: 1, fillStyle: '',
  });
});

const timelineFixture = {
  duration: 5.0,
  cuts: [],
  peaks: [0.4, 0.6, 0.5],
  source_peaks: [0.3, 0.5, 0.4],
  source_video_url: `/outputs/${JOB}/source_video.mp4`,
  dubbed_video_url: `/outputs/${JOB}/dubbed_video.mp4`,
  source_audio_url: `/outputs/${JOB}/audio_16k.wav`,
  dubbed_audio_url: `/outputs/${JOB}/dubbed_audio.wav`,
  segments: [
    { idx: 0, text: 'Hello', original_text: 'Hola', speaker: 'SPEAKER_00',
      start: 0.0, source_start: 0.0, source_end: 1.4, duration: 1.4 },
    { idx: 1, text: 'Bye', original_text: 'Adios', speaker: 'SPEAKER_01',
      start: 1.5, source_start: 1.5, source_end: 2.9, duration: 1.4 },
    { idx: 2, text: 'Again', original_text: 'Otra', speaker: 'SPEAKER_00',
      start: 3.0, source_start: 3.0, source_end: 4.4, duration: 1.4 },
  ],
};

function renderPanel() {
  render(<TimelinePanel job={{ id: JOB }} onApplied={vi.fn()} />);
}

describe('slice at speaker changes', () => {
  it('cuts at every change point in one click', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`, timelineFixture);
    renderPanel();

    const btn = await screen.findByRole('button', { name: /Slice at speaker changes \(2\)/ });
    expect(screen.getByText(/Cuts: none/)).toBeTruthy();

    fireEvent.click(btn);

    // Both change points (1.5s and 3.0s) became cut markers at once.
    const cuts = document.querySelectorAll('[title^="Cut at"]');
    expect(cuts).toHaveLength(2);
    expect(screen.getByText(/Cuts: 00:01, 00:03/)).toBeTruthy();
  });

  it('keeps existing manual cuts and can clear them all', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`,
      { ...timelineFixture, cuts: [4.5] });
    renderPanel();

    await screen.findByRole('button', { name: /Slice at speaker changes/ });
    expect(screen.getByText(/Cuts: 00:04/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Slice at speaker changes/ }));
    // Manual cut at 4.5 survived the union: [1.5, 3.0, 4.5].
    expect(document.querySelectorAll('[title^="Cut at"]')).toHaveLength(3);
    expect(screen.getByText(/Cuts: 00:01, 00:03, 00:04/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Clear cuts' }));
    expect(document.querySelectorAll('[title^="Cut at"]')).toHaveLength(0);
    expect(screen.getByText(/Cuts: none/)).toBeTruthy();
  });

  it('is disabled when there are no change points', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`,
      { ...timelineFixture, segments: [timelineFixture.segments[0]] });
    renderPanel();

    const btn = await screen.findByRole('button', { name: /Slice at speaker changes/ });
    expect(btn.disabled).toBe(true);
  });
});

describe('export turn WAVs', () => {
  it('posts to /turns/export and links the resulting files', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`, timelineFixture);
    setRoute('POST', `/api/dub/${JOB}/turns/export`, {
      ok: true, count: 2, planned: 2,
      turns: [
        { index: 0, start: 0.0, end: 1.5, speaker: 'SPEAKER_00',
          file: 'turn_00_0.00-1.50_SPEAKER_00.wav',
          url: `/outputs/${JOB}/turns/turn_00_0.00-1.50_SPEAKER_00.wav` },
        { index: 1, start: 1.5, end: 5.0, speaker: 'SPEAKER_01',
          file: 'turn_01_1.50-5.00_SPEAKER_01.wav',
          url: `/outputs/${JOB}/turns/turn_01_1.50-5.00_SPEAKER_01.wav` },
      ],
    });
    renderPanel();

    const btn = await screen.findByRole('button', { name: 'Export turn WAVs' });
    fireEvent.click(btn);

    await waitFor(() => expect(
      screen.getByText('2 turn WAVs → turns/'),
    ).toBeTruthy());

    const call = fetchCalls.find(c => c.method === 'POST'
      && c.url === `/api/dub/${JOB}/turns/export`);
    expect(call, 'POST /turns/export was never called').toBeTruthy();

    const link = screen.getByRole('link', { name: /00:00 Speaker 1/ });
    expect(link.getAttribute('href')).toBe(
      `/outputs/${JOB}/turns/turn_00_0.00-1.50_SPEAKER_00.wav`);
  });

  it('shows the server error instead of claiming success', async () => {
    setRoute('GET', `/api/dub/${JOB}/timeline`, timelineFixture);
    setRoute('POST', `/api/dub/${JOB}/turns/export`,
      { error: 'No dubbed_audio.wav yet — apply timing or finish the job first' });
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Export turn WAVs' }));

    await waitFor(() => expect(
      screen.getByText(/No dubbed_audio\.wav yet/),
    ).toBeTruthy());
    expect(screen.queryByText(/turn WAVs → turns\//)).toBeNull();
  });
});
