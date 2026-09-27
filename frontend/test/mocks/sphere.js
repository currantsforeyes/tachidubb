// No-op stand-in for src/sphere.jsx (aliased in vitest.config.mjs).
// WebGL is unavailable in jsdom, and the sphere is decorative — a real
// WebGLRenderer would throw "Error creating WebGL context" on mount.
export function mountSphere() {
  return () => {};
}
