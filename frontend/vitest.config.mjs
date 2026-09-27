// Vitest config for the TachiDUBB UI (see CONTRIBUTING.md > Frontend).
// .mjs because package.json has no "type": "module".
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: [
      // The Tachi sphere is decorative and needs WebGL, which jsdom lacks.
      // Redirect every `../sphere` import to a no-op that returns a cleanup.
      {
        find: /^\.\.\/sphere$/,
        replacement: fileURLToPath(new URL('./test/mocks/sphere.js', import.meta.url)),
      },
    ],
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.js'],
    include: ['test/**/*.test.{js,jsx}'],
  },
  // Explicit rather than relying on Vite defaults: the automatic runtime
  // injects react/jsx-runtime, so test files don't need React in scope.
  esbuild: { jsx: 'automatic' },
});
