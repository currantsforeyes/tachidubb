// TachiDUBB Studio UI — bundled with esbuild into static/dist/app.js.
// Entry point only: the app lives in the modules beside this file
// (app-root.jsx + views/). After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
import * as ReactDOM from 'react-dom/client';
import { App } from './app-root';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App/>);
