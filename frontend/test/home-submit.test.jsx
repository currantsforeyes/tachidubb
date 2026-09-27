// Behavior: the Home form's single-video submit builds the FormData contract
// the backend expects (POST /api/dub) and reports the job id back.
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { HomeView } from '../src/views/home';
import { fetchCalls } from './api.js';

function renderHome(onJobSubmitted = vi.fn()) {
  render(
    <HomeView system={null} voicePresets={[]} sphereOn={false}
              onJobSubmitted={onJobSubmitted}/>,
  );
  return onJobSubmitted;
}

describe('HomeView single-video submit', () => {
  it('disables submit until a URL is provided', () => {
    renderHome();
    // mode defaults to 'url'; empty URL -> CTA explains what's missing.
    const btn = screen.getByRole('button', { name: /Paste a URL/ });
    expect(btn.disabled).toBe(true);
  });

  it('posts FormData with the source URL and language fields to /api/dub', async () => {
    const onJobSubmitted = renderHome();
    const urlInput = screen.getByPlaceholderText(/youtube\.com\/watch/);

    fireEvent.change(urlInput, { target: { value: 'https://youtu.be/dQw4w9WgXcQ' } });

    const btn = screen.getByRole('button', { name: /Start dubbing/ });
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);

    await waitFor(() => expect(onJobSubmitted).toHaveBeenCalledWith('job-test-1'));

    const call = fetchCalls.find(c => c.method === 'POST' && c.url === '/api/dub');
    expect(call, 'POST /api/dub was never called').toBeTruthy();
    expect(call.body).toBeInstanceOf(FormData);
    expect(call.body.get('source')).toBe('https://youtu.be/dQw4w9WgXcQ');
    expect(call.body.get('target_lang')).toBeTruthy();
    expect(call.body.get('model')).toBeTruthy();
    expect(call.body.get('whisper_model')).toBeTruthy();
    // File-mode-only field must not leak into URL submits.
    expect(call.body.get('video')).toBeNull();
  });

  it('uses the file field instead of source when a file is chosen', async () => {
    const onJobSubmitted = renderHome();

    fireEvent.click(screen.getByRole('button', { name: /File/ }));
    const fileInput = document.querySelector('input[type="file"]');
    const file = new File(['x'], 'clip.mp4', { type: 'video/mp4' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Start dubbing/ })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /Start dubbing/ }));
    await waitFor(() => expect(onJobSubmitted).toHaveBeenCalledWith('job-test-1'));

    const call = fetchCalls.find(c => c.method === 'POST' && c.url === '/api/dub');
    expect(call.body.get('video')).toBeInstanceOf(File);
    expect(call.body.get('source')).toBeNull();
  });
});
