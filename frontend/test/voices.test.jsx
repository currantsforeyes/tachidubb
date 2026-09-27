// Behavior: VoicesView renders what the API returns, grouped by type.
import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { VoicesView } from '../src/views/voices';
import { fetchCalls, setRoute } from './api.js';
import { voicePresetFixture } from './fixtures.js';

describe('VoicesView', () => {
  it('renders fetched file presets in the library', async () => {
    setRoute('GET', '/api/voice_presets', {
      presets: [
        voicePresetFixture,
        { ...voicePresetFixture, id: 'vp-2', name: 'Second Voice' },
      ],
    });

    render(<VoicesView/>);

    expect(await screen.findByText('French Narrator')).toBeTruthy();
    expect(screen.getByText('Second Voice')).toBeTruthy();
    // File presets are grouped under the reference-voice section.
    expect(screen.getByText(/reference voice/i)).toBeTruthy();
    expect(fetchCalls.some(c => c.url === '/api/voice_presets')).toBe(true);
  });

  it('renders built-in style presets in their own section', async () => {
    setRoute('GET', '/api/voice_presets', {
      presets: [{ id: 'st-1', type: 'style', name: 'Whisper', style: 'whispery' }],
    });

    render(<VoicesView/>);

    expect(await screen.findByText('Whisper')).toBeTruthy();
    expect(screen.getByText(/Built-in styles/)).toBeTruthy();
    // Styles have no reference audio — no file upload affordance for them.
    expect(screen.queryByText('Replace reference')).toBeNull();
  });

  it('shows the empty library without errors when the API returns nothing', async () => {
    render(<VoicesView/>);
    expect(await screen.findByText('Voice library')).toBeTruthy();
    await waitFor(() =>
      expect(fetchCalls.some(c => c.url === '/api/voice_presets')).toBe(true));
  });
});
