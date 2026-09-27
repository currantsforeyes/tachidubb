// Behavior: HistoryView search + status filtering drive the visible job list.
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { HistoryView } from '../src/views/history';
import { makeJob } from './fixtures.js';

const JOBS = [
  makeJob({ id: 'j1', source_label: 'cat video', status: 'complete' }),
  makeJob({ id: 'j2', source_label: 'dog clip', status: 'error', progress: 40 }),
  makeJob({ id: 'j3', source_label: 'bird song', status: 'translating' }),
];

function renderHistory() {
  return render(
    <HistoryView jobs={JOBS} onJumpProcessing={vi.fn()} onJumpReview={vi.fn()}
                 onJumpResult={vi.fn()} onRefresh={vi.fn()}/>,
  );
}

describe('HistoryView filtering', () => {
  it('renders every job by default', () => {
    renderHistory();
    expect(screen.getByText('cat video')).toBeTruthy();
    expect(screen.getByText('dog clip')).toBeTruthy();
    expect(screen.getByText('bird song')).toBeTruthy();
  });

  it('filters by search text (case-insensitive, matches source_label)', () => {
    renderHistory();
    fireEvent.change(screen.getByPlaceholderText(/Search by title/), {
      target: { value: 'CAT' },
    });

    expect(screen.getByText('cat video')).toBeTruthy();
    expect(screen.queryByText('dog clip')).toBeNull();
    expect(screen.queryByText('bird song')).toBeNull();
  });

  it('shows the resettable no-match state when search misses', () => {
    renderHistory();
    fireEvent.change(screen.getByPlaceholderText(/Search by title/), {
      target: { value: 'zebra' },
    });

    expect(screen.getByText(/No jobs match the filter/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeTruthy();
  });

  it('filters by status tab', () => {
    renderHistory();
    fireEvent.click(screen.getByRole('button', { name: /^Complete/ }));

    expect(screen.getByText('cat video')).toBeTruthy();
    expect(screen.queryByText('dog clip')).toBeNull();
    expect(screen.queryByText('bird song')).toBeNull();
  });

  it('keeps active jobs under the Active tab', () => {
    renderHistory();
    fireEvent.click(screen.getByRole('button', { name: /^Active/ }));

    expect(screen.getByText('bird song')).toBeTruthy();
    expect(screen.queryByText('cat video')).toBeNull();
    expect(screen.queryByText('dog clip')).toBeNull();
  });
});
