// App shell — view routing, job polling, chrome
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
const { useState, useEffect } = React;
import { ACTIVE_STATUSES } from './constants';
import { LeftRail, TopBar } from './nav';
import { BatchView } from './views/batch';
import { EditorView } from './views/editor';
import { GlossaryEditor } from './views/glossary';
import { HistoryView } from './views/history';
import { HomeView } from './views/home';
import { ProcessingView } from './views/processing';
import { ResultView } from './views/result';
import { ReviewView } from './views/review';
import { SystemView } from './views/system';
import { VoicesView } from './views/voices';

// ═══════════════════════════════════════════════════════════════════
// PLACEHOLDER VIEWS — Sessions 2-4 will fill these in.
// They MUST not crash if the user clicks the nav, and they must
// fall back gracefully to the old UI if needed.
// ═══════════════════════════════════════════════════════════════════
export function ComingSoonView({ title, hint, sessionLabel }) {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 14, padding: 40, background: 'var(--bg)' }}>
      <div className="caps">{sessionLabel}</div>
      <div className="serif" style={{ fontSize: 36, letterSpacing: '-0.015em', textAlign: 'center', maxWidth: 480 }}>
        {title}
      </div>
      <div style={{ fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 420, lineHeight: 1.5 }}>
        {hint}
      </div>
      <div style={{
        marginTop: 14, padding: '10px 14px',
        background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 6,
        fontSize: 11.5, color: 'var(--ink-3)',
      }}>
        For now, the original UI for this view still works at the old URL — refresh and use it from there until this view ships.
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// ROOT
// ═══════════════════════════════════════════════════════════════════
export function App() {
  const [view, setView] = useState('home');
  const [system, setSystem] = useState(null);
  const [voicePresets, setVoicePresets] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [sphereOn, setSphereOn] = useState(true);

  // Which job is currently shown on Result / Review. Set when the user
  // clicks "View" / "Review" from History, or auto-set to most recent
  // complete / awaiting_review job otherwise.
  const [selectedResultJobId, setSelectedResultJobId] = useState(null);
  const [selectedReviewJobId, setSelectedReviewJobId] = useState(null);

  // Live system polling — every 5s, just like the old UI
  useEffect(() => {
    const refresh = () => fetch('/api/system').then(r => r.json()).then(setSystem).catch(() => {});
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  // Voice presets — refetched whenever the user switches views so newly
  // uploaded references from the Voices tab show up in the dub form picker.
  useEffect(() => {
    fetch('/api/voices').then(r => r.json()).then(d => setVoicePresets(d.presets || [])).catch(() => {});
  }, [view]);

  // Jobs polling — every 2s when any job is active, else every 10s
  useEffect(() => {
    let stopped = false;
    const fetchJobs = async () => {
      try {
        const r = await fetch('/api/jobs');
        const d = await r.json();
        if (!stopped) setJobs(d.jobs || []);
      } catch (_) {}
    };
    fetchJobs();
    const interval = jobs.some(j => ACTIVE_STATUSES.has(j.status)) ? 2000 : 10000;
    const t = setInterval(fetchJobs, interval);
    return () => { stopped = true; clearInterval(t); };
  }, [jobs.some(j => ACTIVE_STATUSES.has(j.status))]);

  const runningJob = jobs.find(j => ACTIVE_STATUSES.has(j.status));
  const awaitingReviewCount = jobs.filter(j => j.status === 'awaiting_translation_review').length;

  // Keyboard shortcuts: 1-6 switch views, Shift+G toggles sphere
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      if (e.shiftKey && e.key.toLowerCase() === 'g') setSphereOn(s => !s);
      if (!e.metaKey && !e.ctrlKey && !e.shiftKey) {
        if (e.key === '1') setView('home');
        if (e.key === '2') setView('processing');
        if (e.key === '3') setView('review');
        if (e.key === '4') setView('result');
        if (e.key === '5') setView('history');
        if (e.key === '6') setView('batch');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const onJobSubmitted = (jobId) => {
    // After submit, jump to processing so the user sees the live job
    setView('processing');
    // Force-refresh jobs list in case poll hasn't ticked yet
    fetch('/api/jobs').then(r => r.json()).then(d => setJobs(d.jobs || [])).catch(() => {});
  };

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', background: 'var(--bg)' }}>
      <LeftRail
        view={view} setView={setView}
        runningJob={runningJob}
        awaitingReviewCount={awaitingReviewCount}
        system={system}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <TopBar
          view={view}
          runningJob={runningJob}
          awaitingReviewCount={awaitingReviewCount}
          onJumpToProcessing={() => setView('processing')}
          onJumpToReview={() => setView('review')}
        />

        {view === 'home' && (
          <HomeView
            system={system}
            voicePresets={voicePresets}
            sphereOn={sphereOn}
            onJobSubmitted={onJobSubmitted}
          />
        )}

        {view === 'editor' && (
          <EditorView
            jobs={jobs}
            selectedJobId={selectedResultJobId}
            onPickJob={setSelectedResultJobId}
            onSwitchToHome={() => setView('home')}
          />
        )}

        {view === 'processing' && (
          <ProcessingView
            runningJob={runningJob}
            sphereOn={sphereOn}
            onJobCancelled={() => setView('history')}
            onSwitchToHome={() => setView('home')}
          />
        )}

        {view === 'review' && (
          <ReviewView
            jobs={jobs}
            selectedJobId={selectedReviewJobId}
            voicePresets={voicePresets}
            onContinued={() => { setSelectedReviewJobId(null); setView('processing'); }}
            onCancel={() => { setSelectedReviewJobId(null); setView('history'); }}
            onPickJob={setSelectedReviewJobId}
          />
        )}

        {view === 'result' && (
          <ResultView
            jobs={jobs}
            selectedJobId={selectedResultJobId}
            voicePresets={voicePresets}
            onPickJob={setSelectedResultJobId}
            onSwitchToHome={() => setView('home')}
            onSwitchToHistory={() => setView('history')}
          />
        )}

        {view === 'history' && (
          <HistoryView
            jobs={jobs}
            onJumpProcessing={() => setView('processing')}
            onJumpReview={(id) => { setSelectedReviewJobId(id); setView('review'); }}
            onJumpResult={(id) => { setSelectedResultJobId(id); setView('result'); }}
            onRefresh={() => fetch('/api/jobs').then(r => r.json()).then(d => setJobs(d.jobs || []))}
          />
        )}

        {view === 'batch' && (
          <BatchView
            jobs={jobs}
            onRefresh={() => fetch('/api/jobs').then(r => r.json()).then(d => setJobs(d.jobs || []))}
            onJumpProcessing={() => setView('processing')}
            onJumpResult={(id) => { setSelectedResultJobId(id); setView('result'); }}
            onJumpHome={() => setView('home')}
          />
        )}

        {view === 'voices' && <VoicesView/>}

        {view === 'glossary' && <GlossaryEditor/>}

        {view === 'system' && (
          <SystemView system={system} onRefreshSystem={() => fetch('/api/system').then(r => r.json()).then(setSystem)}/>
        )}
      </div>

      {/* Sphere on/off tweak strip */}
      <div style={{
        position: 'fixed', bottom: 12, right: 16,
        padding: '6px 10px',
        background: 'var(--bg-2)', border: '1px solid var(--line)',
        borderRadius: 999,
        display: 'flex', alignItems: 'center', gap: 10,
        fontSize: 10, fontFamily: 'var(--mono)',
        color: 'var(--ink-4)', zIndex: 10,
      }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={sphereOn} onChange={e => setSphereOn(e.target.checked)} style={{ accentColor: 'var(--accent)' }}/>
          sphere
        </label>
        <span style={{ color: 'var(--ink-4)' }}>·</span>
        <span>1-6 views · ⇧G sphere</span>
      </div>
    </div>
  );
}

