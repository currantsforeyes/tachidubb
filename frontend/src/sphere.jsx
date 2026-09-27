// Tachi signature icosahedron (three.js, tree-shaken)
// Part of frontend/src/ — module map in CONTRIBUTING.md. After editing, run:
//   npm --prefix frontend run build
import * as React from 'react';
// Named imports so esbuild tree-shakes three.js down to what we actually use.
import {
  Color,
  IcosahedronGeometry,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  ShaderMaterial,
  WebGLRenderer,
} from 'three';

const THREE = {
  Color,
  IcosahedronGeometry,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  ShaderMaterial,
  WebGLRenderer,
};

// ═══════════════════════════════════════════════════════════════════
// SPHERE — Tachi signature. Lightweight icosahedron with rim glow.
// Mounted only on Home + Processing per scoping survey decision.
// ═══════════════════════════════════════════════════════════════════
export function mountSphere(el, opts) {
  const { variant = 'idle', size = 220 } = opts || {};
  if (!el || typeof THREE === 'undefined') {
    el.innerHTML = `<div style="width:${size}px;height:${size}px;border-radius:50%;
      border:1px solid var(--line-2);background:radial-gradient(circle at 30% 30%,
      var(--bg-2),var(--bg) 70%);"></div>`;
    return () => { el.innerHTML = ''; };
  }
  const palette = variant === 'live'
    ? { core: 0xccff66, rim: 0x88dd44, breath: 1.6 }
    : { core: 0x9ab4d4, rim: 0x5a7094, breath: 3.2 };

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0, 5.2);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.setSize(size, size);
  el.appendChild(renderer.domElement);

  const geo = new THREE.IcosahedronGeometry(1.4, 3);
  const mat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uCore: { value: new THREE.Color(palette.core) }, uRim: { value: new THREE.Color(palette.rim) } },
    vertexShader: `
      varying vec3 vNormal; varying vec3 vPos;
      uniform float uTime;
      float noise(vec3 p) {
        return sin(p.x*2.0+uTime*0.7)*0.5 + cos(p.y*1.7+uTime*0.5)*0.5 + sin(p.z*2.3+uTime*0.6)*0.3;
      }
      void main() {
        vNormal = normal; vPos = position;
        float n = noise(position*0.8) * 0.12;
        vec3 d = position + normal * n;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(d, 1.0);
      }`,
    fragmentShader: `
      varying vec3 vNormal; varying vec3 vPos;
      uniform vec3 uCore; uniform vec3 uRim; uniform float uTime;
      void main() {
        vec3 view = normalize(cameraPosition - vPos);
        float rim = pow(1.0 - max(dot(vNormal, view), 0.0), 2.2);
        float pulse = 0.5 + 0.5 * sin(uTime * 0.5);
        vec3 col = mix(uCore * 0.25, uRim, rim);
        col *= 0.8 + pulse * 0.3;
        gl_FragColor = vec4(col, 0.95);
      }`,
    transparent: true, depthWrite: false,
  });
  const mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);
  const halo = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.7, 2),
    new THREE.MeshBasicMaterial({ color: palette.rim, wireframe: true, transparent: true, opacity: variant === 'live' ? 0.35 : 0.18 })
  );
  scene.add(halo);

  let t0 = performance.now(); let raf;
  const tick = () => {
    const t = (performance.now() - t0) * 0.001;
    mat.uniforms.uTime.value = t * palette.breath;
    mesh.rotation.y = t * 0.12; mesh.rotation.x = Math.sin(t * 0.2) * 0.08;
    halo.rotation.y = -t * 0.06;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => {
    cancelAnimationFrame(raf);
    renderer.dispose(); geo.dispose(); mat.dispose();
    halo.geometry.dispose(); halo.material.dispose();
    if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
  };
}

