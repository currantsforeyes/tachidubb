// Inline SVG icon set
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';

// ═══════════════════════════════════════════════════════════════════
// ICONS
// ═══════════════════════════════════════════════════════════════════
export const I = {
  home:       <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2 7l6-5 6 5v7H2z"/><path d="M6 14V9h4v5"/></svg>,
  processing: <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="5.5"/><path d="M8 4.5v3.5l2.5 1.5"/></svg>,
  review:     <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M5 6h6M5 8.5h6M5 11h4"/></svg>,
  result:     <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="2" y="3.5" width="12" height="9" rx="1.5"/><path d="M7 7v3l2.5-1.5z" fill="currentColor" stroke="none"/></svg>,
  history:    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M8 2.5a5.5 5.5 0 1 1-5.45 4.8M2 2v3.5h3.5"/><path d="M8 5v3.5L10.5 10"/></svg>,
  batch:      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="2" y="2.5" width="9" height="9" rx="1.4"/><rect x="5" y="5.5" width="9" height="9" rx="1.4"/></svg>,
  system:     <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="2"/><path d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.5 3.5l-1.4 1.4M4.9 11.1l-1.4 1.4M12.5 12.5l-1.4-1.4M4.9 4.9L3.5 3.5"/></svg>,
  upload:     <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M8 2v9m0-9l-3 3m3-3l3 3M2.5 14h11"/></svg>,
  link:       <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M6 4H4.5A2.5 2.5 0 1 0 4.5 11H6M10 11h1.5A2.5 2.5 0 1 0 11.5 6H10M5.5 7.5h5"/></svg>,
  plus:       <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M6 2v8M2 6h8"/></svg>,
  cancel:     <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="6" cy="6" r="4.5"/><path d="M4.2 4.2l3.6 3.6"/></svg>,
  check:      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2.5 6.5l2.5 2.5 5-6"/></svg>,
  search:     <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><circle cx="5" cy="5" r="3.5"/><path d="M7.6 7.6L11 11"/></svg>,
  cpu:        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><rect x="3" y="3" width="6" height="6" rx="1"/><path d="M5 1v1.5M7 1v1.5M5 9.5V11M7 9.5V11M1 5h1.5M1 7h1.5M9.5 5H11M9.5 7H11"/></svg>,
  arrow:      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M3 6h6m0 0L6.5 3.5M9 6L6.5 8.5"/></svg>,
  copy:       <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1"/><path d="M2 8.5V2.5h6"/></svg>,
  refresh:    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M2 6a4 4 0 0 1 7-2.6M10 6a4 4 0 0 1-7 2.6M9 1.5V4H6.5M3 10.5V8h2.5"/></svg>,
  trash:      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M2 3h8M5 1.5h2M3.5 3v7.5h5V3M5 5v4M7 5v4"/></svg>,
  star:       <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" stroke="currentColor" strokeWidth="0.8"><path d="M6 1.5l1.5 3 3.3.5-2.4 2.3.6 3.3L6 9l-3 1.6.6-3.3L1.2 5l3.3-.5z"/></svg>,
  starOff:    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M6 1.5l1.5 3 3.3.5-2.4 2.3.6 3.3L6 9l-3 1.6.6-3.3L1.2 5l3.3-.5z"/></svg>,
  eye:        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M1 6s1.7-3.5 5-3.5S11 6 11 6s-1.7 3.5-5 3.5S1 6 1 6z"/><circle cx="6" cy="6" r="1.4"/></svg>,
  folder:     <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M1.5 3.5c0-.5.4-1 1-1H5l1 1.5h4c.5 0 1 .4 1 1V9.5c0 .5-.4 1-1 1H2.5c-.5 0-1-.5-1-1z"/></svg>,
  edit:       <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M1.5 10.5L4 10l5.7-5.7-2-2L2 8l-.5 2.5z"/></svg>,
  warn:       <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M6 1.5L11 10.5H1zM6 5v3M6 9v.6"/></svg>,
  voice:      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3 8a5 5 0 0 0 10 0M8 13v1.5M5.5 14.5h5"/></svg>,
  glossary:   <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2.5 3.5c1.5-1 4-1 5.5 0 1.5-1 4-1 5.5 0v9c-1.5-1-4-1-5.5 0-1.5-1-4-1-5.5 0zM8 3.5v9"/></svg>,
};

