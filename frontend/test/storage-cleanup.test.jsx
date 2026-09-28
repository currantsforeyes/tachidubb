// Behavior: the System → Storage cleanup controls.
//   1. The preview must render the server's real response keys
//      (`affected` / `mb_freed`). The UI used to read `affected_count` /
//      `freed_mb`, names the server never emits, so every preview claimed
//      "0 job(s), ? MB" and the buttons looked broken.
//   2. The "All" preset posts older_than_days=0, so jobs created today can
//      actually be cleared (the old 1-day minimum excluded them all).
import { describe, expect, it } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { SysStorage } from '../src/views/system';
import { fetchCalls, setRoute } from './api.js';

const STATS = {
  total_gb: 1.2,
  job_count: 3,
  jobs: [{ id: 'a', label: 'demo.mp4', size_mb: 500, age_days: 0,
           target_lang: 'fr', starred: false }],
};

// Exactly what app/routers/storage.py returns — the shape under test.
const CLEANUP_OK = {
  dry_run: true, mode: 'intermediate', candidates: 3, affected: 2,
  bytes_freed: 13107200, mb_freed: 12.5, gb_freed: 0.01,
  details: [], errors: [],
};

const flatText = (container) => container.textContent.replace(/\s+/g, ' ');

const renderStorage = async () => {
  const view = render(<SysStorage />);
  await screen.findByRole('button', { name: /Preview cleanup/ });
  return view;
};

describe('storage cleanup', () => {
  it('shows the counts from the keys the server actually sends', async () => {
    setRoute('GET', '/api/storage/stats', STATS);
    setRoute('POST', '/api/storage/cleanup', CLEANUP_OK);
    const { container } = await renderStorage();

    fireEvent.click(screen.getByRole('button', { name: /Preview cleanup/ }));

    await waitFor(() => expect(
      flatText(container).includes('Would delete 2 job(s), free 12.5 MB'),
      'preview did not show the server counts — wrong response keys?',
    ).toBe(true));

    // Execute is offered, and gated on the preview actually matching jobs.
    expect(screen.getByRole('button', { name: /Execute cleanup/ }).disabled)
      .toBe(false);
  });

  it('sends older_than_days=0 when "All" is picked', async () => {
    setRoute('GET', '/api/storage/stats', STATS);
    setRoute('POST', '/api/storage/cleanup', CLEANUP_OK);
    await renderStorage();

    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    fireEvent.click(screen.getByRole('button', { name: /Preview cleanup/ }));

    await waitFor(() => {
      const call = fetchCalls.find(c => c.method === 'POST'
        && c.url === '/api/storage/cleanup');
      expect(call, 'cleanup was never called').toBeTruthy();
      expect(call.body.get('older_than_days')).toBe('0');
    });
  });

  it('disables Execute instead of confirming a no-op delete', async () => {
    setRoute('GET', '/api/storage/stats', STATS);
    setRoute('POST', '/api/storage/cleanup',
      { ...CLEANUP_OK, candidates: 0, affected: 0, bytes_freed: 0, mb_freed: 0 });
    await renderStorage();

    fireEvent.click(screen.getByRole('button', { name: /Preview cleanup/ }));

    await waitFor(() => expect(
      screen.getByText(/Nothing matches these rules/),
    ).toBeTruthy());
    expect(screen.getByRole('button', { name: /Execute cleanup/ }).disabled)
      .toBe(true);
  });
});
