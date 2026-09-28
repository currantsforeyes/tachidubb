// Behavior: the dialogue editor's track order and honesty badges.
//
// The requested layout puts the two *separated* reference stems on top —
// source speech (original language, not translated), then the background bed
// — followed by the text lanes and the translated speaker tracks. Jobs
// without stems must say so rather than silently showing the full mix.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { TimelinePanel } from '../src/views/editor';
import { setRoute } from './api.js';

const JOB = 'lanejob';

// jsdom has no canvas: give WaveformLane the no-op 2d context it needs.
beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = () => ({
    setTransform() {}, clearRect() {}, fillRect() {},
    globalAlpha: 1, fillStyle: '',
  });
});

const baseFixture = {
  duration: 4.0,
  cuts: [],
  peaks: [0.4, 0.6],
  source_peaks: [0.3, 0.5],
  source_video_url: `/outputs/${JOB}/source_video.mp4`,
  dubbed_video_url: `/outputs/${JOB}/dubbed_video.mp4`,
  source_audio_url: `/outputs/${JOB}/audio_16k.wav`,
  dubbed_audio_url: `/outputs/${JOB}/dubbed_audio.wav`,
  segments: [
    { idx: 0, text: 'Bonjour', original_text: 'Hello', speaker: 'SPEAKER_00',
      start: 0.0, source_start: 0.0, source_end: 1.4, duration: 1.4 },
  ],
};

const withStems = {
  ...baseFixture,
  speech_peaks: [0.9, 0.2], speech_stem: true, bg_peaks: [0.1, 0.4],
};

const withoutStems = {
  ...baseFixture,
  speech_peaks: baseFixture.source_peaks, speech_stem: false, bg_peaks: [],
};

const renderTimeline = async (fixture) => {
  setRoute('GET', `/api/dub/${JOB}/timeline`, fixture);
  render(<TimelinePanel job={{ id: JOB }} onApplied={vi.fn()} />);
  await screen.findByText('Source Speech');
};

const expectInOrder = (labels) => {
  const els = labels.map(t => screen.getByText(t));
  for (let i = 1; i < els.length; i++) {
    const follows = els[i - 1].compareDocumentPosition(els[i])
      & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(follows, `${labels[i]} should come after ${labels[i - 1]}`).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  }
};

describe('editor reference lanes', () => {
  it('stacks source speech, then background, then text and speaker tracks', async () => {
    await renderTimeline(withStems);

    expectInOrder(['Source Speech', 'Background', 'Original Text',
                   'Translated Text']);
  });

  it('serves the separated stems without an honesty badge', async () => {
    await renderTimeline(withStems);

    expect(screen.queryByText('full mix')).toBeNull();
    expect(screen.queryByText('no stem')).toBeNull();
  });

  it('flags a job that has no stems', async () => {
    await renderTimeline(withoutStems);

    // speech lane falls back to the full mix — say so rather than pretend.
    expect(screen.getByText('full mix')).toBeTruthy();
    expect(screen.getByText('no stem')).toBeTruthy();
    expect(screen.getByText(/No separated background/)).toBeTruthy();
  });
});
