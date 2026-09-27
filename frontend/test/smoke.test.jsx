// Smoke tests: every view module + the App shell renders without throwing.
//
// "Renders without crashing" is exactly the regression class a module split
// introduces — a missing import or undefined symbol crashes at module scope
// or first render. Behavior lives in the sibling *.test.jsx files.
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { App } from '../src/app-root';
import { BatchView } from '../src/views/batch';
import { EditorView } from '../src/views/editor';
import { GlossaryEditor } from '../src/views/glossary';
import { HistoryView } from '../src/views/history';
import { HomeView } from '../src/views/home';
import { ExportPanel } from '../src/views/panels';
import { ProcessingView } from '../src/views/processing';
import { ResultView } from '../src/views/result';
import { ReviewView } from '../src/views/review';
import { SystemView } from '../src/views/system';
import { VoicesView } from '../src/views/voices';
import { makeJob } from './fixtures.js';

const noop = vi.fn;

describe('view smoke tests', () => {
  it('HomeView renders the hero and form', () => {
    render(
      <HomeView system={null} voicePresets={[]} sphereOn={false}
                onJobSubmitted={noop()}/>,
    );
    expect(screen.getByText('New dub')).toBeTruthy();
    expect(screen.getByText('Source media')).toBeTruthy();
  });

  it('ProcessingView shows the empty state without a running job', () => {
    render(
      <ProcessingView runningJob={null} sphereOn={false}
                      onJobCancelled={noop()} onSwitchToHome={noop()}/>,
    );
    expect(screen.getByText('No active job')).toBeTruthy();
  });

  it('HistoryView shows the empty state', () => {
    render(
      <HistoryView jobs={[]} onJumpProcessing={noop()} onJumpReview={noop()}
                   onJumpResult={noop()} onRefresh={noop()}/>,
    );
    expect(screen.getByText(/No jobs yet/)).toBeTruthy();
  });

  it('ResultView shows the empty state', () => {
    render(
      <ResultView jobs={[]} selectedJobId={null} voicePresets={[]}
                  onPickJob={noop()} onSwitchToHome={noop()}
                  onSwitchToHistory={noop()}/>,
    );
    expect(screen.getByText('No completed jobs yet')).toBeTruthy();
  });

  it('EditorView shows the empty state', () => {
    render(
      <EditorView jobs={[]} selectedJobId={null} onPickJob={noop()}
                  onSwitchToHome={noop()}/>,
    );
    expect(screen.getByText('No completed jobs yet')).toBeTruthy();
  });

  it('ReviewView shows the empty state', () => {
    render(
      <ReviewView jobs={[]} selectedJobId={null} voicePresets={[]}
                  onContinued={noop()} onCancel={noop()} onPickJob={noop()}/>,
    );
    expect(screen.getByText('No reviews pending')).toBeTruthy();
  });

  it('BatchView shows the empty state', () => {
    render(
      <BatchView jobs={[]} onRefresh={noop()} onJumpProcessing={noop()}
                 onJumpResult={noop()} onJumpHome={noop()}/>,
    );
    expect(screen.getByText('No batches yet')).toBeTruthy();
  });

  it('SystemView renders while system status is still loading', () => {
    render(<SystemView system={null} onRefreshSystem={noop()}/>);
    expect(screen.getAllByText('System').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Loading/)).toBeTruthy();
  });

  it('VoicesView renders the library shell', async () => {
    render(<VoicesView/>);
    expect(await screen.findByText('Voice library')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Upload reference voice/ })).toBeTruthy();
  });

  it('GlossaryEditor renders the overrides editor', async () => {
    render(<GlossaryEditor/>);
    expect(await screen.findByText('Translation overrides')).toBeTruthy();
  });

  it('ExportPanel lists platform presets', () => {
    render(<ExportPanel job={makeJob()}/>);
    expect(screen.getByText('YouTube 1080p')).toBeTruthy();
  });

  it('App renders the shell with nav and home view', async () => {
    render(<App/>);
    expect(await screen.findByText('New dub')).toBeTruthy();
    expect(screen.getAllByText('Home').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Processing').length).toBeGreaterThanOrEqual(1);
  });
});
