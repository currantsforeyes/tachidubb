// Behavior: cutting the audio track in the dialogue editor.
//
// Three complaints under test:
//   1. A misplaced marker had no usable way back off the screen — the only
//      target was the 2px line itself, and there was no "undo what I just
//      placed".
//   2. "Slice at speaker changes" only dropped markers; nothing indicated
//      that the slices were now real, movable pieces of audio.
//   3. The slices could not be dragged into alignment.
//
// A section is the span between two cut lines. Dragging one moves every clip
// that starts inside it by the same delta and leaves its neighbours alone
// (non-ripple), which is the placements payload "Apply timing to video" saves.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { TimelinePanel } from '../src/views/editor';
import { setRoute } from './api.js';

const JOB = 'cutjob';
const PX = 26; // the panel's default pxPerSec

// jsdom has no canvas: give WaveformLane the no-op 2d context it needs.
beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = () => ({
    setTransform() {}, clearRect() {}, fillRect() {},
    globalAlpha: 1, fillStyle: '',
  });
});

// Two speakers alternating -> speaker-change points at 2.0 and 4.0.
const makeFixture = (cuts) => ({
  duration: 6.0,
  cuts,
  peaks: [0.4, 0.6],
  source_peaks: [0.3, 0.5],
  source_video_url: `/outputs/${JOB}/source_video.mp4`,
  dubbed_video_url: `/outputs/${JOB}/dubbed_video.mp4`,
  source_audio_url: `/outputs/${JOB}/audio_16k.wav`,
  dubbed_audio_url: `/outputs/${JOB}/dubbed_audio.wav`,
  segments: [
    { idx: 0, text: 'Alpha', original_text: 'A-orig', speaker: 'SPEAKER_00',
      start: 0.0, source_start: 0.0, source_end: 1.4, duration: 1.4 },
    { idx: 1, text: 'Bravo', original_text: 'B-orig', speaker: 'SPEAKER_01',
      start: 2.0, source_start: 2.0, source_end: 3.4, duration: 1.4 },
    { idx: 2, text: 'Charlie', original_text: 'C-orig', speaker: 'SPEAKER_00',
      start: 4.0, source_start: 4.0, source_end: 5.4, duration: 1.4 },
  ],
});

const renderEditor = async (fixture) => {
  setRoute('GET', `/api/dub/${JOB}/timeline`, fixture);
  render(<TimelinePanel job={{ id: JOB }} onApplied={vi.fn()} />);
  // The cuts summary only renders once the timeline has loaded, and it shows
  // for every fixture (including "Cuts: none").
  await screen.findByText(/Cuts:/);
};

// queryAllByTitle: "no markers" must yield [] rather than throw like getAll*.
const markers = () => screen.queryAllByTitle(/click to remove/);
const sectionBlocks = (matcher) => screen.getAllByTitle(matcher);
// The translated-lane clip for a line of dialogue (title === its text).
const clipLeft = (text) => parseFloat(screen.getByTitle(text).style.left);

describe('cut markers', () => {
  it('removes a single marker when it is clicked', async () => {
    await renderEditor(makeFixture([2.0, 4.0]));
    expect(markers()).toHaveLength(2);

    fireEvent.click(markers()[0]);

    expect(markers()).toHaveLength(1);
    expect(markers()[0].getAttribute('title')).toContain('00:04');
  });

  it('offers a hittable × handle on the ruler for each marker', async () => {
    await renderEditor(makeFixture([2.0, 4.0]));

    const handles = screen.getAllByTitle(/Remove cut at /);
    expect(handles).toHaveLength(2);

    fireEvent.click(handles[1]);

    expect(markers()).toHaveLength(1);
    expect(markers()[0].getAttribute('title')).toContain('00:02');
  });

  it('clears every marker from the toolbar button', async () => {
    await renderEditor(makeFixture([2.0, 4.0]));

    fireEvent.click(screen.getByRole('button', { name: 'Clear cuts' }));

    expect(screen.queryByTitle(/click to remove/)).toBeNull();
  });

  it('takes back an auto-slice one marker at a time with Undo cut', async () => {
    await renderEditor(makeFixture([]));
    expect(markers()).toHaveLength(0);
    // Markers loaded from the server were not placed by this session, so
    // there is nothing to undo yet.
    expect(screen.queryByRole('button', { name: 'Undo cut' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Slice at speaker changes/ }));
    expect(markers()).toHaveLength(2);   // speaker changes at 2.0 and 4.0

    fireEvent.click(screen.getByRole('button', { name: 'Undo cut' }));
    expect(markers()).toHaveLength(1);
    expect(markers()[0].getAttribute('title')).toContain('00:02');

    fireEvent.click(screen.getByRole('button', { name: 'Undo cut' }));
    expect(screen.queryByTitle(/click to remove/)).toBeNull();
  });

  it('keeps Undo in step with a marker removed by hand', async () => {
    await renderEditor(makeFixture([]));
    fireEvent.click(screen.getByRole('button', { name: /Slice at speaker changes/ }));

    // Remove the newest marker via its × handle; the undo stack must not
    // then try to remove it a second time.
    fireEvent.click(screen.getAllByTitle(/Remove cut at /)[1]);

    fireEvent.click(screen.getByRole('button', { name: 'Undo cut' }));
    expect(screen.queryByTitle(/click to remove/)).toBeNull();
  });
});

describe('sections', () => {
  it('appears over the waveform only once there are cuts', async () => {
    await renderEditor(makeFixture([]));
    expect(screen.queryByTitle(/^Section/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Slice at speaker changes/ }));

    // 3 sections x 2 speaker lanes.
    expect(sectionBlocks(/^Section 1 of 3/)).toHaveLength(2);
    expect(sectionBlocks(/^Section 3 of 3/)).toHaveLength(2);
  });

  it('drags every clip inside the section and leaves the rest alone', async () => {
    await renderEditor(makeFixture([2.0, 4.0]));
    expect(clipLeft('Bravo')).toBeCloseTo(2 * PX, 3);
    expect(clipLeft('Charlie')).toBeCloseTo(4 * PX, 3);

    const [block] = sectionBlocks(/^Section 2 of 3/);
    fireEvent.pointerDown(block, { clientX: 100, pointerId: 1 });
    fireEvent.pointerMove(block, { clientX: 130, pointerId: 1 }); // +30px

    // Live feedback: the block reports the offset it is being moved by.
    // One label per speaker lane carries the same section.
    expect(screen.getAllByText('+1.15s').length).toBeGreaterThan(0);
    // Its own clip moved by the dragged distance…
    expect(clipLeft('Bravo') - 2 * PX).toBeCloseTo(30, 0);
    // …and the neighbour did not (non-ripple).
    expect(clipLeft('Charlie')).toBeCloseTo(4 * PX, 3);
    expect(clipLeft('Alpha')).toBeCloseTo(0, 3);

    fireEvent.pointerUp(block, { clientX: 130, pointerId: 1 });
    // The move survives the gesture ending (it is what Apply saves).
    expect(clipLeft('Bravo') - 2 * PX).toBeCloseTo(30, 0);
  });

  it('ignores a plain click so seeking still works under a block', async () => {
    await renderEditor(makeFixture([2.0, 4.0]));
    const [block] = sectionBlocks(/^Section 2 of 3/);

    fireEvent.pointerDown(block, { clientX: 100, pointerId: 1 });
    fireEvent.pointerMove(block, { clientX: 101, pointerId: 1 }); // under the 3px threshold
    fireEvent.pointerUp(block, { clientX: 101, pointerId: 1 });

    expect(clipLeft('Bravo')).toBeCloseTo(2 * PX, 3);
    expect(screen.queryAllByText(/^[+-]\d+\.\d\ds$/)).toHaveLength(0);
  });
});
