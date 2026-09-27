// Behavior: status → stage mapping and the StatusBadge label/color contract.
// These are the pure decisions behind the Processing view's stage chain and
// every status pill in History/Batch.
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { stageForStatus, STATUS_META, ACTIVE_STATUSES } from '../src/constants';
import { StatusBadge } from '../src/ui';

describe('stageForStatus', () => {
  it('maps each pipeline status to its stage index', () => {
    expect(stageForStatus('queued')).toBe(0);
    expect(stageForStatus('downloading')).toBe(0);
    expect(stageForStatus('transcribing')).toBe(1);
    expect(stageForStatus('diarizing')).toBe(1);
    expect(stageForStatus('translating')).toBe(2);
    expect(stageForStatus('awaiting_translation_review')).toBe(3);
    expect(stageForStatus('synthesizing')).toBe(4);
    expect(stageForStatus('merging')).toBe(5);
    expect(stageForStatus('complete')).toBe(6);
  });

  it('returns -1 for idle/unknown statuses', () => {
    expect(stageForStatus('error')).toBe(-1);
    expect(stageForStatus('cancelled')).toBe(-1);
    expect(stageForStatus('nonsense')).toBe(-1);
  });
});

describe('StatusBadge', () => {
  it('shows the mapped label for a known status', () => {
    render(<StatusBadge status="complete"/>);
    expect(screen.getByText(STATUS_META.complete.label)).toBeTruthy();
  });

  it('falls back to the raw status string when unmapped', () => {
    render(<StatusBadge status="made_up_status"/>);
    expect(screen.getByText('made_up_status')).toBeTruthy();
  });

  it('marks active statuses as pulsing and complete as static', () => {
    const { container: active } = render(<StatusBadge status="transcribing"/>);
    const activePill = active.querySelector('span[style*="animation"]');
    expect(activePill.style.animation).toContain('pulse');

    const { container: done } = render(<StatusBadge status="complete"/>);
    const donePill = done.querySelector('span[style*="animation"]');
    expect(donePill.style.animation).toContain('none');
  });

  it('every status the UI can receive has meta or falls back safely', () => {
    // Guards STATUS_META staying in sync with the backend's status vocabulary:
    // any active status must have an entry (the badge shows its label).
    for (const status of ACTIVE_STATUSES) {
      expect(STATUS_META[status], `missing STATUS_META entry for ${status}`).toBeTruthy();
    }
  });
});
