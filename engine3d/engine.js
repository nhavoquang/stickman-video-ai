// Bộ dựng phim hoạt hình 3D (three.js) — thế giới low-poly tô toon + viền mực, cỏ/hoa dày, bầu trời có mặt trời,
// mờ hậu cảnh khi quay cận, nhân vật đầu trứng thân que có biểu cảm; phụ đề vẽ chồng lên trong trình duyệt.
// Dựng từng khung qua Chromium (Playwright, WebGL phần mềm). Định dạng phim: xem prompts/film3d_spec.md.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const W = window.FRAME_W || 1080, H = window.FRAME_H || 1920;
const SS = window.SUPERSAMPLE || 1.5; // dựng to hơn rồi thu nhỏ → nét căng, không răng cưa
const RW = Math.round(W * SS), RH = Math.round(H * SS);
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(RW, RH);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
const out2d = document.createElement('canvas'); out2d.width = W; out2d.height = H;
const o2 = out2d.getContext('2d');

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 3000);
const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(RW, RH, { type: THREE.HalfFloatType, samples: 4 }));
composer.addPass(new RenderPass(scene, camera));
const bokeh = new BokehPass(scene, camera, { focus: 10, aperture: 0.0001, maxblur: 0.005 });
composer.addPass(bokeh);
composer.addPass(new OutputPass());

let seed = 11;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const pick = (a) => a[Math.floor(rnd() * a.length)];

// ---------- vật liệu ----------
function gradTex(vals) {
  const t = new THREE.DataTexture(new Uint8Array(vals), vals.length, 1, THREE.RedFormat);
  t.minFilter = t.magFilter = THREE.NearestFilter; t.needsUpdate = true; return t;
}
const GRAD = gradTex([140, 185, 225, 255]);          // thế giới: 4 bậc sáng
const GRAD_SOFT = (() => {                           // nhân vật: bóng mềm (dải mượt)
  const n = 64, a = []; for (let i = 0; i < n; i++) a.push(Math.round(170 + 85 * Math.pow(i / (n - 1), 0.8)));
  const t = new THREE.DataTexture(new Uint8Array(a), n, 1, THREE.RedFormat);
  t.minFilter = t.magFilter = THREE.LinearFilter; t.needsUpdate = true; return t;
})();
const MATS = {};
const toon = (color, soft = false, extra = {}) => {
  const k = color + (soft ? 's' : '') + JSON.stringify(extra, (kk, v) => (v && v.isColor ? v.getHexString() : v));
  return MATS[k] || (MATS[k] = new THREE.MeshToonMaterial({ color, gradientMap: soft ? GRAD_SOFT : GRAD, ...extra }));
};
const basic = (color) => MATS['b' + color] || (MATS['b' + color] = new THREE.MeshBasicMaterial({ color }));
const INK = new THREE.MeshBasicMaterial({ color: 0x141414, side: THREE.BackSide });
function inked(mesh, w = 0.035) {
  mesh.castShadow = true; mesh.receiveShadow = true;
  const o = new THREE.Mesh(mesh.geometry, INK); o.scale.setScalar(1 + w); o.castShadow = false; o.userData.ink = true;
  mesh.add(o); return mesh;
}
const box = (w, h, d, c, ink = 0.03) => inked(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof c === 'object' ? c : toon(c)), ink);
const cyl = (r1, r2, h, c, seg = 12, ink = 0.03) => inked(new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), toon(c)), ink);
const at = (m, x, y, z) => { m.position.set(x, y, z); return m; };

// ---------- bầu trời + ánh sáng ----------
const LIGHTS = {
  sunny:  { top: 0x2f7fe0, mid: 0x8cc4ff, bot: 0xe3f1ff, sun: 0xfff1d6, sunI: 2.7, amb: 0xcfe3ff, gnd: 0x5d7a3a, ambI: 1.15, fog: 0xcfe2f5, az: 215, el: 38, fogN: 90, fogF: 650 },
  golden: { top: 0x3a4f9a, mid: 0xf08a4b, bot: 0xffd59a, sun: 0xffb46a, sunI: 2.5, amb: 0xffd2b0, gnd: 0x6a4a3a, ambI: 0.95, fog: 0xf2c49c, az: 250, el: 9, fogN: 70, fogF: 560 },
  storm:  { top: 0x141a26, mid: 0x2c3548, bot: 0x56627a, sun: 0xa8b8d8, sunI: 0.9, amb: 0x6a7896, gnd: 0x2a3326, ambI: 1.0, fog: 0x3a4459, az: 200, el: 55, fogN: 25, fogF: 260 },
  night:  { top: 0x02061a, mid: 0x0c1838, bot: 0x22335c, sun: 0x8fa8ff, sunI: 0.55, amb: 0x3a4a78, gnd: 0x101820, ambI: 0.75, fog: 0x0e1730, az: 160, el: 35, fogN: 40, fogF: 380 },
  indoor: { top: 0xf3e6cf, mid: 0xf3e6cf, bot: 0xe6d3b3, sun: 0xffe9c4, sunI: 1.6, amb: 0xfff2dd, gnd: 0x8a6a4a, ambI: 1.3, fog: 0xeadcc4, az: 200, el: 60, fogN: 60, fogF: 300 },
};
const skyMat = new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, fog: false,
  uniforms: { top: { value: new THREE.Color() }, mid: { value: new THREE.Color() }, bot: { value: new THREE.Color() }, sunDir: { value: new THREE.Vector3() }, sunCol: { value: new THREE.Color() } },
  vertexShader: 'varying vec3 p; void main(){ p = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }',
  fragmentShader: `uniform vec3 top; uniform vec3 mid; uniform vec3 bot; uniform vec3 sunDir; uniform vec3 sunCol; varying vec3 p;
    void main(){ float y = p.y; vec3 c = y < 0.12 ? mix(bot, mid, smoothstep(-0.02, 0.12, y)) : mix(mid, top, smoothstep(0.12, 0.7, y));
      float s = max(dot(p, normalize(sunDir)), 0.0); c += sunCol * (pow(s, 600.0) * 1.6 + pow(s, 12.0) * 0.28);
      gl_FragColor = vec4(c, 1.); }`,
});
const sky = new THREE.Mesh(new THREE.SphereGeometry(2500, 32, 16), skyMat); sky.renderOrder = -1;
scene.add(sky);
const sun = new THREE.DirectionalLight(0xffffff, 2);
sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
sun.shadow.bias = -0.0003; sun.shadow.normalBias = 0.03; sun.shadow.radius = 4;
scene.add(sun, sun.target);
const amb = new THREE.HemisphereLight(0xffffff, 0x6b8a4a, 1);
scene.add(amb);
scene.fog = new THREE.Fog(0xffffff, 60, 600);
const fill = new THREE.PointLight(0xffffff, 0, 30, 2); scene.add(fill); // đèn phụ (nội thất xe, đêm)
function setLight(name, focus, camPos) {
  const L = LIGHTS[name] || LIGHTS.sunny;
  skyMat.uniforms.top.value.set(L.top); skyMat.uniforms.mid.value.set(L.mid); skyMat.uniforms.bot.value.set(L.bot);
  sun.color.set(L.sun); sun.intensity = L.sunI; amb.color.set(L.amb); amb.groundColor.set(L.gnd); amb.intensity = L.ambI;
  scene.fog.color.set(L.fog); scene.fog.near = L.fogN; scene.fog.far = L.fogF;
  const az = L.az * Math.PI / 180, el = L.el * Math.PI / 180;
  const dir = new THREE.Vector3(Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az));
  skyMat.uniforms.sunDir.value.copy(dir); skyMat.uniforms.sunCol.value.set(L.sun);
  sky.position.copy(camPos);
  // bóng đổ bám theo chỗ máy quay đang nhìn, vùng bóng nhỏ khi quay cận cho sắc nét
  const span = Math.min(120, Math.max(18, focus.distanceTo(camPos) * 1.4));
  Object.assign(sun.shadow.camera, { left: -span, right: span, top: span, bottom: -span, near: 1, far: 600 });
  sun.shadow.camera.updateProjectionMatrix();
  sun.position.copy(focus).addScaledVector(dir, 200); sun.target.position.copy(focus);
  fill.intensity = name === 'night' || name === 'storm' ? 6 : 0; fill.position.copy(camPos).add(new THREE.Vector3(0, 1.5, 0));
}

// ---------- thư viện đồ vật ----------
const P = {};
P.ground = (o) => { const g = new THREE.PlaneGeometry(6000, 6000); g.rotateX(-Math.PI / 2); const m = new THREE.Mesh(g, toon(o.color ?? 0x7cb342)); m.receiveShadow = true; return m; };
P.field = (o) => {
  const grp = new THREE.Group(), n = o.rows || 40, w = o.w || 400, d = o.d || 1600;
  const cs = o.colors || [0xd9c46c, 0xc4ae55];
  for (let i = 0; i < n; i++) { const m = new THREE.Mesh(new THREE.BoxGeometry(w / n * 0.9, 0.35 + (i % 2) * 0.15, d), toon(cs[i % cs.length])); m.position.set(-w / 2 + (i + 0.5) * w / n, 0.2, 0); m.receiveShadow = true; grp.add(m); }
  return grp;
};
P.road = (o) => {
  const grp = new THREE.Group(), len = o.len || 1600, w = o.w || 7.5;
  grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(w + 1.6, 0.12, len), toon(0x8a7f6a)), 0, 0.3, 0));                // lề sỏi
  const a = at(new THREE.Mesh(new THREE.BoxGeometry(w, 0.12, len), toon(0x45484e)), 0, 0.36, 0); a.receiveShadow = true; grp.add(a);
  for (const s of [-1, 1]) grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.13, len), basic(0xeeeeee)), s * (w / 2 - 0.4), 0.37, 0));
  for (const s of [-0.12, 0.12]) grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.13, len), basic(0xf2c230)), s, 0.37, 0));
  return grp;
};
P.street = (o) => { const g = P.road({ ...o, w: o.w || 12 }); g.add(at(new THREE.Mesh(new THREE.BoxGeometry(3, 0.4, o.len || 1600), toon(0xb8b2a6)), (o.w || 12) / 2 + 1.5, 0.3, 0)); g.add(at(new THREE.Mesh(new THREE.BoxGeometry(3, 0.4, o.len || 1600), toon(0xb8b2a6)), -(o.w || 12) / 2 - 1.5, 0.3, 0)); return g; };
P.grass = (o) => { // thảm cỏ + hoa (instanced), rải trong hình chữ nhật w×d quanh pos
  const grp = new THREE.Group(), w = o.w || 30, d = o.d || 30, n = Math.min(60000, Math.round((o.density || 40) * w * d / 10));
  const blade = new THREE.ConeGeometry(0.05, 0.32, 3); blade.translate(0, 0.16, 0);
  const im = new THREE.InstancedMesh(blade, toon(0xffffff), n);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), c = new THREE.Color();
  const greens = o.colors || [0x6aa83a, 0x7dbb45, 0x5c9631, 0x8cc552, 0x4f8a2c];
  for (let i = 0; i < n; i++) {
    const x = (rnd() - 0.5) * w, z = (rnd() - 0.5) * d, s = 0.6 + rnd() * 1.1;
    if (o.avoid && Math.abs(x + (o.pos?.[0] || 0) - o.avoid[0]) < o.avoid[1]) continue;
    e.set((rnd() - 0.5) * 0.5, rnd() * 6.3, (rnd() - 0.5) * 0.5); q.setFromEuler(e);
    m.compose(new THREE.Vector3(x, 0.3, z), q, new THREE.Vector3(s, s * (0.7 + rnd() * 0.8), s)); im.setMatrixAt(i, m);
    im.setColorAt(i, c.set(pick(greens)));
  }
  im.receiveShadow = true; grp.add(im);
  const nf = Math.round(n * (o.flowers ?? 0.02));
  if (nf) {
    const fg = new THREE.IcosahedronGeometry(0.11, 0); fg.translate(0, 0.6, 0);
    const fm = new THREE.InstancedMesh(fg, toon(0xffffff), nf);
    const fc = o.flowerColors || [0xffffff, 0xffd23f, 0xff6b9a, 0xb388ff];
    for (let i = 0; i < nf; i++) { m.makeTranslation((rnd() - 0.5) * w, 0, (rnd() - 0.5) * d); fm.setMatrixAt(i, m); fm.setColorAt(i, c.set(pick(fc))); }
    grp.add(fm);
  }
  return grp;
};
P.tree = (o) => {
  const grp = new THREE.Group(), s = o.size || 1, kind = o.kind || 'oak';
  if (kind === 'pine') {
    grp.add(at(cyl(0.3 * s, 0.45 * s, 3 * s, 0x6b4a2e, 7), 0, 1.5 * s, 0));
    for (let i = 0; i < 4; i++) grp.add(at(inked(new THREE.Mesh(new THREE.ConeGeometry((3.2 - i * 0.7) * s, 3.2 * s, 8), toon(i % 2 ? 0x2f6b3a : 0x3a7d44)), 0.03), 0, (3.5 + i * 1.7) * s, 0));
    return grp;
  }
  const trunk = inked(new THREE.Mesh(new THREE.CylinderGeometry(0.5 * s, 1.0 * s, 6.5 * s, 9), toon(0x6e4b2f)), 0.05); trunk.position.y = 3.2 * s; grp.add(trunk);
  for (const a of [0.6, 2.4, 4.3]) { const b = inked(new THREE.Mesh(new THREE.CylinderGeometry(0.18 * s, 0.32 * s, 3.4 * s, 6), toon(0x6e4b2f)), 0.05); b.position.set(Math.cos(a) * 1.2 * s, 6.8 * s, Math.sin(a) * 1.2 * s); b.rotation.set(Math.sin(a) * 0.7, 0, -Math.cos(a) * 0.7); grp.add(b); }
  const leaves = o.leaves || [0x4f8f2f, 0x5fa83a, 0x6dbb44, 0x467f2a];
  for (let i = 0; i < 16; i++) {
    const r = (1.6 + rnd() * 1.5) * s, a = rnd() * Math.PI * 2, d = (i < 2 ? 0.5 : 2.2 + rnd() * 1.6) * s;
    const b = inked(new THREE.Mesh(new THREE.IcosahedronGeometry(r, 1), toon(pick(leaves), false, { flatShading: true })), 0.025);
    b.position.set(Math.cos(a) * d, (8 + rnd() * 3 - d * 0.25) * s, Math.sin(a) * d); b.rotation.set(rnd() * 3, rnd() * 3, 0); grp.add(b);
  }
  return grp;
};
P.bush = (o) => { const grp = new THREE.Group(), s = o.size || 1; for (let i = 0; i < 5; i++) grp.add(at(inked(new THREE.Mesh(new THREE.IcosahedronGeometry((0.7 + rnd() * 0.5) * s, 1), toon(pick([0x4f8f2f, 0x5fa83a]), false, { flatShading: true })), 0.03), (rnd() - 0.5) * 1.6 * s, 0.7 * s, (rnd() - 0.5) * 1.2 * s)); return grp; };
P.rock = (o) => at(inked(new THREE.Mesh(new THREE.DodecahedronGeometry(o.size || 0.8, 0), toon(0x8d8a84, false, { flatShading: true }))), 0, (o.size || 0.8) * 0.5, 0);
P.cloud = (o) => { const grp = new THREE.Group(), s = o.size || 1, m = new THREE.MeshLambertMaterial({ color: 0xffffff, emissive: 0x9aa7b8, fog: false }); for (let i = 0; i < 7; i++) { const b = new THREE.Mesh(new THREE.IcosahedronGeometry((7 + rnd() * 6) * s, 2), m); b.position.set((i * 7 - 21) * s, (rnd() * 4 - (i % 3 ? 0 : 2)) * s, rnd() * 6 * s); b.scale.y = 0.7; grp.add(b); } return grp; };
P.fence = (o) => { const grp = new THREE.Group(), len = o.len || 40; for (let z = -len / 2; z <= len / 2; z += 2.5) grp.add(at(cyl(0.07, 0.07, 1.3, 0x7a6a55, 6, 0.04), 0, 0.65, z)); for (const y of [0.6, 1.1]) grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.03, len), basic(0x444444)), 0, y, 0)); return grp; };
P.pole = (o) => { const grp = new THREE.Group(); grp.add(at(cyl(0.15, 0.2, 9, 0x7a5a3a, 8), 0, 4.5, 0)); grp.add(at(box(2.4, 0.15, 0.15, 0x7a5a3a), 0, 8.4, 0)); return grp; };
function textTexture(text, { bg = '#c8102e', fg = '#ffffff', border = '#ffffff', w = 512, h = 384, font = 'Arial Black, Arial' } = {}) {
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h; const x = cv.getContext('2d');
  x.fillStyle = bg; x.fillRect(0, 0, w, h); if (border) { x.strokeStyle = border; x.lineWidth = h * 0.04; x.strokeRect(h * 0.04, h * 0.04, w - h * 0.08, h - h * 0.08); }
  x.fillStyle = fg; x.textAlign = 'center'; x.textBaseline = 'middle';
  const lines = String(text || '').split('\n'), fs = Math.min(h * 0.32, h * 0.8 / lines.length);
  x.font = `900 ${fs}px ${font}`; lines.forEach((l, i) => x.fillText(l, w / 2, h / 2 + (i - (lines.length - 1) / 2) * fs * 1.05, w * 0.9));
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}
P.sign = (o) => { // biển đứng 2 cột, chữ vẽ bằng code (luôn đúng chính tả)
  const grp = new THREE.Group(), h = o.h || 2.5, bw = o.w || 3.4, bh = o.bh || bw * 0.75;
  for (const s of [-1, 1]) grp.add(at(cyl(0.08, 0.08, h + bh / 2, 0x8a8a8a, 8), s * bw * 0.35, (h + bh / 2) / 2, 0));
  const face = new THREE.MeshBasicMaterial({ map: textTexture(o.text, { bg: o.bg || '#c8102e', fg: o.fg || '#fff' }) });
  grp.add(at(inked(new THREE.Mesh(new THREE.BoxGeometry(bw, bh, 0.12), [toon(0xdddddd), toon(0xdddddd), toon(0xdddddd), toon(0xdddddd), face, toon(0xdddddd)]), 0.03), 0, h + bh / 2, 0));
  return grp;
};
P.billboard = (o) => { const g = P.sign({ ...o, h: o.h || 5, w: o.w || 8, bh: o.bh || 4, bg: o.bg || '#f7e8b0', fg: o.fg || '#b8261e' }); return g; };
P.marquee = (o) => { // biển đèn chớp kiểu Mỹ: khung mũi tên + bóng đèn phát sáng
  const grp = new THREE.Group(), s = o.size || 1;
  grp.add(at(cyl(0.12 * s, 0.12 * s, 3 * s, 0x5a5a5a, 8), 0, 1.5 * s, 0));
  const face = new THREE.MeshBasicMaterial({ map: textTexture(o.text || "DON'T\nHIT\nTHIS", { bg: '#f6e7c1', fg: '#c1121f', border: '#c1121f', w: 384, h: 512 }) });
  grp.add(at(inked(new THREE.Mesh(new THREE.BoxGeometry(2.4 * s, 3.2 * s, 0.3 * s), [toon(0xc1121f), toon(0xc1121f), toon(0xc1121f), toon(0xc1121f), face, toon(0xc1121f)]), 0.03), 0, 4.8 * s, 0));
  const arc = inked(new THREE.Mesh(new THREE.TorusGeometry(2.6 * s, 0.32 * s, 8, 24, Math.PI * 1.25), toon(0xc1121f)), 0.04); arc.position.set(-0.3 * s, 4.8 * s, 0); arc.rotation.z = Math.PI * 0.55; grp.add(arc);
  const bulbs = []; const bg = new THREE.SphereGeometry(0.1 * s, 8, 6);
  for (let i = 0; i < 26; i++) { const a = Math.PI * 0.55 + i / 25 * Math.PI * 1.25; const b = new THREE.Mesh(bg, new THREE.MeshBasicMaterial({ color: 0xfff1a8 })); b.position.set(-0.3 * s + Math.cos(a) * 2.6 * s, 4.8 * s + Math.sin(a) * 2.6 * s, 0.35 * s); grp.add(b); bulbs.push(b); }
  grp.userData.tick = (t) => bulbs.forEach((b, i) => b.material.color.set(((i + Math.floor(t * 8)) % 3) ? 0xfff1a8 : 0x8a5a20));
  return grp;
};
P.house = (o) => {
  const grp = new THREE.Group(), w = o.w || 8, d = o.d || 7, h = o.h || 4, col = o.color ?? pick([0xf2e3c6, 0xd9e6f2, 0xf6d6c4, 0xe1ecd3]);
  grp.add(at(box(w, h, d, col), 0, h / 2, 0));
  const roof = new THREE.Mesh(new THREE.CylinderGeometry(0, w * 0.75, h * 0.55, 4, 1), toon(o.roof ?? 0xa8432f)); roof.rotation.y = Math.PI / 4; roof.scale.z = d / w; inked(roof, 0.03); grp.add(at(roof, 0, h + h * 0.27, 0));
  grp.add(at(box(1.3, 2.2, 0.15, 0x7a4a2a), 0, 1.1, d / 2 + 0.05));
  for (const x of [-w * 0.3, w * 0.3]) grp.add(at(box(1.4, 1.2, 0.12, 0x9fd3f0), x, h * 0.6, d / 2 + 0.05));
  return grp;
};
P.shop = (o) => { // cửa hàng phố nhỏ: mặt tiền gạch + biển tên
  const grp = new THREE.Group(), w = o.w || 9, h = o.h || 7, d = o.d || 8;
  grp.add(at(box(w, h, d, o.color ?? pick([0xb5563a, 0xc9a26b, 0x8a6f5a, 0xd4b48c])), 0, h / 2, 0));
  grp.add(at(box(w * 0.8, 2.4, 0.15, 0x9fd3f0), 0, 1.6, d / 2 + 0.05));
  grp.add(at(box(w + 0.6, 0.4, 0.6, 0xf2f2f2), 0, h + 0.2, 0));
  if (o.text) { const face = new THREE.MeshBasicMaterial({ map: textTexture(o.text, { bg: o.bg || '#1f5c3a', fg: '#f3d36b', border: '#f3d36b', w: 768, h: 192 }) }); grp.add(at(new THREE.Mesh(new THREE.PlaneGeometry(w * 0.85, w * 0.21), face), 0, h * 0.62, d / 2 + 0.1)); }
  return grp;
};
P.tower = (o) => { const grp = new THREE.Group(); grp.add(at(cyl(2, 3, 14, 0x9a9a9a, 12), 0, 7, 0)); grp.add(at(cyl(4, 4, 3, 0xb0b0b0, 14), 0, 15, 0)); return grp; };
function wheelSet(grp, xs, zs, r = 0.45) { for (const x of xs) for (const z of zs) { const w = inked(new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.35, 16), toon(0x1c1c1c))); w.rotation.z = Math.PI / 2; grp.add(at(w, x, r, z)); grp.add(at(new THREE.Mesh(new THREE.CylinderGeometry(r * 0.5, r * 0.5, 0.37, 10), toon(0xbbbbbb)), x, r, z).rotateZ(Math.PI / 2)); } }
P.car = (o) => {
  const grp = new THREE.Group(), col = o.color ?? 0xd8d8d8;
  grp.add(at(box(2, 0.85, 4.4, col), 0, 0.95, 0));
  grp.add(at(box(1.8, 0.75, 2.3, col), 0, 1.75, -0.25));
  const gl = toon(0x2b3a4a);
  grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(1.84, 0.5, 2.0), gl), 0, 1.78, -0.25));
  for (const s of [-1, 1]) grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.18, 0.06), basic(0xfff6c8)), s * 0.65, 1.0, 2.22));
  wheelSet(grp, [-1, 1], [1.4, -1.4]);
  return grp;
};
P.police_car = (o) => {
  const grp = P.car({ color: 0xf4f4f4 });
  grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(2.02, 0.4, 2.2), toon(0x1f6b3a)), 0, 0.85, -0.1));        // sọc xanh kiểu sheriff
  const bar = new THREE.Group(); bar.add(at(box(1.3, 0.18, 0.35, 0x222222), 0, 0, 0));
  const red = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.2, 0.33), new THREE.MeshBasicMaterial({ color: 0xff2a2a }));
  const blue = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.2, 0.33), new THREE.MeshBasicMaterial({ color: 0x2a6bff }));
  bar.add(at(red, -0.32, 0.1, 0), at(blue, 0.32, 0.1, 0)); grp.add(at(bar, 0, 2.22, -0.25));
  const star = new THREE.Mesh(new THREE.CircleGeometry(0.25, 5), basic(0xd4a017)); star.rotation.y = Math.PI / 2; grp.add(at(star, 1.02, 1.05, 0.2));
  grp.userData.tick = (t) => { const on = Math.floor(t * 6) % 2; red.material.color.set(on ? 0xff2a2a : 0x551010); blue.material.color.set(on ? 0x10204a : 0x2a6bff); };
  return grp;
};
P.truck = (o) => {
  const grp = new THREE.Group(), col = o.color ?? 0xd32f2f;
  grp.add(at(box(2.3, 2.0, 2.4, col), 0, 1.6, 2.2)); grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(2.32, 0.8, 1.2), toon(0x2b3a4a)), 0, 2.0, 2.9));
  grp.add(at(box(2.3, 0.6, 4.6, 0xeeeeee), 0, 0.95, -1.3)); grp.add(at(box(0.25, 2.4, 0.25, 0x333333), 0, 2.2, -3.3));
  if (o.text) { const f = new THREE.MeshBasicMaterial({ map: textTexture(o.text, { bg: '#ffffff', fg: '#c1121f', border: null, w: 512, h: 256 }) }); const p = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 1.1), f); p.rotation.y = Math.PI / 2; grp.add(at(p, 1.17, 1.7, 2.2)); }
  wheelSet(grp, [-1.1, 1.1], [2.2, -1.0, -2.6], 0.5);
  return grp;
};
P.cockpit = (o) => { // nội thất xe nhìn từ ghế lái (đặt máy quay ngay sau, cao ~1.25)
  const grp = new THREE.Group(), dark = 0x2a2a2e;
  grp.add(at(box(2.2, 0.5, 0.9, dark, 0.01), 0, 0.95, -0.2));                                     // táp-lô
  grp.add(at(box(2.3, 0.08, 0.08, 0x111111, 0), 0, 2.1, -0.6));                                    // nóc kính
  for (const s of [-1, 1]) { const a = box(0.12, 1.3, 0.12, 0x111111, 0); a.rotation.z = s * 0.25; grp.add(at(a, s * 1.05, 1.55, -0.55)); }
  const wheel = inked(new THREE.Mesh(new THREE.TorusGeometry(0.32, 0.045, 10, 28), toon(0x18181a)), 0.03); wheel.rotation.x = -1.1; grp.add(at(wheel, -0.38, 1.15, 0.15));
  grp.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.45), toon(0x18181a)), -0.38, 1.12, 0.05));
  for (const x of [-0.55, -0.22]) { const g = new THREE.Mesh(new THREE.CircleGeometry(0.11, 20), basic(0x9fd3ff)); g.rotation.x = -0.4; grp.add(at(g, x, 1.21, -0.18)); }
  grp.userData.wheel = wheel;
  return grp;
};

// ---------- nhân vật: đầu trứng to, thân que, bóng mềm ----------
function faceTexture(expr) {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1024;
  const x = cv.getContext('2d'); x.scale(2, 2); x.strokeStyle = x.fillStyle = '#141414'; x.lineCap = 'round'; x.lineJoin = 'round';
  const E = { neutral: { b: 0, eye: 'dot', m: 'flat' }, happy: { b: -10, eye: 'arc', m: 'smile' }, laugh: { b: -14, eye: 'arc', m: 'open' },
    angry: { b: 18, eye: 'dot', m: 'frown', red: true }, shock: { b: -22, eye: 'big', m: 'o' }, smug: { b: 6, eye: 'half', m: 'smirk' },
    sad: { b: -8, eye: 'dot', m: 'frown', tilt: true }, scared: { b: -18, eye: 'big', m: 'wavy', sweat: true }, think: { b: 8, eye: 'dot', m: 'side' } }[expr] || { b: 0, eye: 'dot', m: 'flat' };
  for (const s of [-1, 1]) {
    const ex = 256 + s * 72, ey = 232;
    if (E.eye === 'big') { x.fillStyle = '#fff'; x.beginPath(); x.arc(ex, ey, 34, 0, 7); x.fill(); x.lineWidth = 7; x.stroke(); x.fillStyle = '#141414'; x.beginPath(); x.arc(ex, ey, 12, 0, 7); x.fill(); }
    else if (E.eye === 'arc') { x.lineWidth = 14; x.beginPath(); x.arc(ex, ey + 10, 20, Math.PI * 1.1, Math.PI * 1.9); x.stroke(); }
    else if (E.eye === 'half') { x.beginPath(); x.arc(ex, ey, 17, 0, Math.PI); x.fill(); x.lineWidth = 9; x.beginPath(); x.moveTo(ex - 22, ey); x.lineTo(ex + 22, ey); x.stroke(); }
    else { if (E.red) { x.fillStyle = '#e02020'; x.beginPath(); x.arc(ex, ey, 26, 0, 7); x.fill(); x.fillStyle = '#141414'; } x.beginPath(); x.arc(ex, ey, 17, 0, 7); x.fill(); }
    x.lineWidth = 17; x.beginPath();                                       // lông mày dày
    const inner = 256 + s * 34, outer = 256 + s * 112, by = 172;
    x.moveTo(inner, by + E.b * 0.9 + (E.tilt ? -12 : 0)); x.lineTo(outer, by - E.b * 0.5 + (E.tilt ? 10 : 0)); x.stroke();
  }
  x.lineWidth = 13; x.beginPath();
  const my = 330;
  if (E.m === 'smile') x.arc(256, my - 30, 50, 0.18 * Math.PI, 0.82 * Math.PI);
  else if (E.m === 'open') { x.moveTo(196, my - 10); x.quadraticCurveTo(256, my + 90, 316, my - 10); x.closePath(); x.fill(); }
  else if (E.m === 'frown') x.arc(256, my + 48, 44, 1.2 * Math.PI, 1.8 * Math.PI);
  else if (E.m === 'o') { x.ellipse(256, my + 10, 24, 34, 0, 0, 7); x.fill(); }
  else if (E.m === 'smirk') { x.moveTo(210, my); x.quadraticCurveTo(270, my + 14, 304, my - 22); }
  else if (E.m === 'wavy') { x.moveTo(206, my); for (let i = 0; i < 5; i++) x.quadraticCurveTo(216 + i * 20, my + (i % 2 ? 14 : -14), 226 + i * 20, my); }
  else if (E.m === 'side') { x.moveTo(236, my); x.lineTo(292, my - 8); }
  else { x.moveTo(220, my); x.lineTo(292, my); }
  x.stroke();
  if (E.sweat) { x.fillStyle = '#7fc8ff'; x.beginPath(); x.moveTo(390, 140); x.quadraticCurveTo(420, 200, 390, 210); x.quadraticCurveTo(360, 200, 390, 140); x.fill(); }
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}
const FACES = {};
const faceTex = (e) => FACES[e] || (FACES[e] = faceTexture(e));
P.character = (o) => {
  const grp = new THREE.Group(), s = o.size || 1;
  const rig = new THREE.Group(); grp.add(rig);
  const headGeo = new THREE.SphereGeometry(0.62, 40, 30);
  const head = inked(new THREE.Mesh(headGeo, toon(o.skin ?? 0xfbfaf6, true, { emissive: new THREE.Color(o.skin ?? 0xfbfaf6).multiplyScalar(0.38) })), 0.06);
  head.receiveShadow = false;
  head.scale.set(1, 1.12, 0.96); head.position.y = 2.42; rig.add(head);
  // mặt: decal bám theo mặt cầu (đúng phối cảnh, có bóng mềm của đầu nhờ blending multiply)
  const fgeo = new THREE.SphereGeometry(0.625, 40, 30, Math.PI * 0.15, Math.PI * 0.7, Math.PI * 0.18, Math.PI * 0.62);
  const face = new THREE.Mesh(fgeo, new THREE.MeshBasicMaterial({ map: faceTex(o.expr || 'neutral'), transparent: true, depthWrite: false }));
  head.add(face); grp.userData.face = face;
  const shirt = toon(o.shirt ?? 0x2a9d8f, true);
  const torso = inked(new THREE.Mesh(new THREE.CapsuleGeometry(0.27, 0.5, 6, 16), shirt), 0.05); torso.position.y = 1.5; torso.scale.set(1, 1, 0.85); rig.add(torso);
  if (o.pants) rig.add(at(inked(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.25, 0.28, 16), toon(o.pants, true)), 0.05), 0, 1.13, 0));
  const limbM = toon(0x161616, true);
  const mkLimb = (x, y, len, hand) => { const p = new THREE.Group(); p.position.set(x, y, 0); const l = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.04, len, 6), limbM); l.castShadow = true; l.position.y = -len / 2; p.add(l); if (hand) { const h = new THREE.Mesh(new THREE.SphereGeometry(0.08, 10, 8), limbM); h.position.y = -len; p.add(h); } else { const f = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.12, 4, 8), limbM); f.rotation.x = Math.PI / 2; f.position.set(0, -len, 0.06); p.add(f); } rig.add(p); return p; };
  grp.userData.legs = [mkLimb(-0.12, 1.08, 1.02), mkLimb(0.12, 1.08, 1.02)];
  grp.userData.arms = [mkLimb(-0.3, 1.82, 0.85, true), mkLimb(0.3, 1.82, 0.85, true)];
  const hc = o.hatColor ?? 0xd62828;
  if (o.hat === 'cap') { const c = inked(new THREE.Mesh(new THREE.SphereGeometry(0.645, 28, 14, 0, 7, 0, 1.25), toon(hc, true)), 0.04); c.position.y = 0.12; head.add(c); head.add(at(inked(new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.05, 0.5), toon(hc, true)), 0.04), 0, 0.47, 0.6)); }
  else if (o.hat === 'sheriff' || o.hat === 'cowboy') { const b = inked(new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.0, 0.05, 28), toon(o.hatColor ?? 0x7a5230, true)), 0.04); b.position.y = 0.52; b.scale.z = 0.85; head.add(b); head.add(at(inked(new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.52, 0.48, 22), toon(o.hatColor ?? 0x7a5230, true)), 0.04), 0, 0.76, 0)); if (o.hat === 'sheriff') { const st = new THREE.Mesh(new THREE.CircleGeometry(0.1, 5), basic(0xd4a017)); torso.add(at(st, -0.13, 0.15, 0.24)); } }
  else if (o.hat === 'chef') { head.add(at(inked(new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.45, 0.8, 22), toon(0xffffff, true)), 0.04), 0, 0.75, 0)); }
  else if (o.hat === 'tophat') { head.add(at(inked(new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 0.05, 24), toon(0x1a1a1a, true)), 0.04), 0, 0.5, 0)); head.add(at(inked(new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.8, 22), toon(0x1a1a1a, true)), 0.04), 0, 0.9, 0)); }
  else if (o.hat === 'hardhat') { const c = inked(new THREE.Mesh(new THREE.SphereGeometry(0.68, 28, 14, 0, 7, 0, 1.35), toon(o.hatColor ?? 0xf2c230, true)), 0.04); c.position.y = 0.1; head.add(c); }
  if (o.mustache) { const m = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.05, 6, 12, Math.PI), basic(0x3a2a1a)); head.add(at(m, 0, -0.18, 0.6)); }
  if (o.glasses) { for (const s2 of [-1, 1]) { const g = new THREE.Mesh(new THREE.TorusGeometry(0.13, 0.025, 6, 18), basic(0x141414)); head.add(at(g, s2 * 0.2, 0.04, 0.6)); } }
  grp.traverse((m) => { if (m.isMesh && m !== head) m.receiveShadow = false; }); // nhân vật luôn sáng rõ, không bị bóng cây phủ xám
  grp.scale.setScalar(s);
  grp.userData.rig = rig; grp.userData.head = head;
  return grp;
};
P.chair = (o) => { const grp = new THREE.Group(), c = o.color ?? 0x2f8f6a; grp.add(at(box(0.9, 0.08, 0.9, c), 0, 0.55, 0)); grp.add(at(box(0.9, 0.9, 0.08, c), 0, 1.0, -0.42)); for (const x of [-0.4, 0.4]) for (const z of [-0.4, 0.4]) grp.add(at(cyl(0.03, 0.03, 0.55, 0xaaaaaa, 6), x, 0.27, z)); return grp; };

// ---------- dựng thế giới ----------
const objs = {};
export function build(world) {
  seed = world.seed || 11;
  for (const it of world.objects) {
    const f = P[it.type]; if (!f) { console.error('Không có loại đồ vật: ' + it.type); continue; }
    const m = f(it);
    m.position.set(...(it.pos || [0, 0, 0]));
    if (it.rot) m.rotation.y = it.rot * Math.PI / 180;
    if (it.scale) m.scale.multiplyScalar(it.scale);
    scene.add(m);
    if (it.id) objs[it.id] = { mesh: m, def: it };
    else if (m.userData.tick) objs['_' + Object.keys(objs).length] = { mesh: m, def: it };
  }
}

// ---------- chuyển động ----------
const lerp = (a, b, k) => a + (b - a) * k;
const ease = (k) => k * k * (3 - 2 * k);
function track(keys, t, smooth = true) {
  if (!keys || !keys.length) return null;
  if (t <= keys[0][0]) return keys[0].slice(1);
  for (let i = 1; i < keys.length; i++) if (t <= keys[i][0]) {
    const raw = (t - keys[i - 1][0]) / Math.max(1e-6, keys[i][0] - keys[i - 1][0]), k = smooth ? ease(raw) : raw;
    return keys[i].slice(1).map((v, j) => typeof v === 'number' ? lerp(keys[i - 1][j + 1], v, k) : keys[i - 1][j + 1]);
  }
  return keys[keys.length - 1].slice(1);
}
function actPose(o, act, t, t0) {
  const u = o.mesh.userData; if (!u.legs) return;
  const [L, R] = u.legs, [AL, AR] = u.arms, rig = u.rig, head = u.head;
  const lt = t - t0; let w = 0, bob = 0;
  L.rotation.set(0, 0, 0); R.rotation.set(0, 0, 0); AL.rotation.set(0, 0, 0.12); AR.rotation.set(0, 0, -0.12); rig.rotation.set(0, 0, 0); rig.position.set(0, 0, 0); head.rotation.set(0, 0, 0);
  const breathe = Math.sin(t * 2.2) * 0.015; rig.position.y = breathe;
  switch (act) {
    case 'walk': w = Math.sin(lt * 8) * 0.55; bob = Math.abs(Math.sin(lt * 8)) * 0.06; break;
    case 'run': w = Math.sin(lt * 13) * 0.9; bob = Math.abs(Math.sin(lt * 13)) * 0.12; rig.rotation.x = 0.18; break;
    case 'point': AR.rotation.set(-1.5, 0, -0.1); break;
    case 'wave': AR.rotation.set(0, 0, -2.6 + Math.sin(lt * 10) * 0.35); break;
    case 'cheer': AR.rotation.z = -2.7 + Math.sin(lt * 12) * 0.2; AL.rotation.z = 2.7 - Math.sin(lt * 12) * 0.2; bob = Math.abs(Math.sin(lt * 7)) * 0.35; break;
    case 'shrug': AR.rotation.z = -1.0; AL.rotation.z = 1.0; head.rotation.z = 0.12; break;
    case 'angry': AR.rotation.set(-0.3, 0, -0.5 + Math.sin(lt * 18) * 0.15); AL.rotation.set(-0.3, 0, 0.5 - Math.sin(lt * 18) * 0.15); rig.rotation.x = 0.1; bob = Math.abs(Math.sin(lt * 9)) * 0.05; break;
    case 'think': AR.rotation.set(-2.3, 0, 0.6); head.rotation.z = 0.15; break;
    case 'sit': L.rotation.x = -1.5; R.rotation.x = -1.5; rig.position.y = -0.55; break;
    case 'fall': rig.rotation.x = -Math.min(1.5, lt * 4); break;
    case 'shock': AR.rotation.z = -0.9; AL.rotation.z = 0.9; bob = Math.max(0, 0.25 - lt) * 0.8; break;
    case 'talk': AR.rotation.set(-0.6 + Math.sin(lt * 5) * 0.25, 0, -0.3); head.rotation.x = Math.sin(lt * 7) * 0.04; break;
    case 'drive': L.rotation.x = -1.4; R.rotation.x = -1.4; AR.rotation.x = -1.2; AL.rotation.x = -1.2; break;
    default: AR.rotation.x = Math.sin(t * 1.3) * 0.05; head.rotation.y = Math.sin(t * 0.7) * 0.06;
  }
  L.rotation.x += w; R.rotation.x -= w; AL.rotation.x -= w * 0.8; AR.rotation.x += w * 0.8; rig.position.y += bob;
}

// ---------- phụ đề ----------
function drawCaption(text) {
  if (!text) return;
  const vertical = H > W, fs = Math.round((vertical ? 62 : 54) * (vertical ? W / 1080 : H / 1080));
  o2.save(); o2.font = `800 ${fs}px "Montserrat", "Arial Black", Arial, sans-serif`; o2.textAlign = 'center'; o2.textBaseline = 'middle';
  o2.lineJoin = 'round'; o2.lineWidth = fs * 0.2; o2.strokeStyle = 'rgba(0,0,0,0.9)';
  const y = H * (vertical ? 0.69 : 0.86);
  o2.shadowColor = 'rgba(0,0,0,0.45)'; o2.shadowBlur = fs * 0.25; o2.shadowOffsetY = fs * 0.06;
  o2.strokeText(text, W / 2, y, W * 0.88); o2.shadowColor = 'transparent';
  o2.fillStyle = '#ffffff'; o2.fillText(text, W / 2, y, W * 0.88); o2.restore();
}

// ---------- một khung ----------
export function frame(film, t) {
  const shots = film.shots;
  const shot = shots.find((s) => t >= s.t0 && t < s.t1) || shots[shots.length - 1];
  const k = Math.min(1, Math.max(0, (t - shot.t0) / Math.max(0.1, shot.t1 - shot.t0)));
  const kk = shot.cam.ease === 'linear' ? k : 0.75 * k + 0.25 * ease(k);
  const c = shot.cam, to = c.to || c.from;
  const pos = new THREE.Vector3(...c.from.map((v, i) => lerp(v, to[i], kk)));
  const look = new THREE.Vector3(...c.look.map((v, i) => lerp(v, (c.lookTo || c.look)[i], kk)));
  if (c.follow && objs[c.follow]) { const fp = objs[c.follow].mesh.position; pos.add(fp); look.add(fp); }
  if (c.shake) { pos.x += Math.sin(t * 37) * c.shake * 0.05; pos.y += Math.sin(t * 29) * c.shake * 0.05; }
  camera.fov = lerp(c.fov || 40, c.fovTo || c.fov || 40, kk); camera.updateProjectionMatrix();
  camera.position.copy(pos); camera.lookAt(look);
  if (c.roll) camera.rotateZ(c.roll * Math.PI / 180);
  setLight(shot.light || film.light || 'sunny', look, pos);
  // mờ hậu cảnh: lấy nét vào điểm nhìn; càng cận càng mờ nền (như ống kính thật)
  const dist = pos.distanceTo(look);
  bokeh.uniforms.focus.value = dist;
  bokeh.uniforms.aperture.value = c.dof === false ? 0 : (c.dof ?? (dist < 6 ? 0.0025 : dist < 12 ? 0.0009 : 0));
  bokeh.uniforms.maxblur.value = 0.005;
  for (const [id, o] of Object.entries(objs)) {
    if (o.mesh.userData.tick) o.mesh.userData.tick(t);
    const a = (film.anim || {})[id]; if (!a) { if (o.mesh.userData.legs) actPose(o, 'idle', t, 0); continue; }
    const p = track(a.pos, t, a.smooth !== false); if (p) o.mesh.position.set(...p);
    const r = track(a.rot, t); if (r) o.mesh.rotation.y = r[0] * Math.PI / 180;
    if (a.face && objs[a.face]) { const tp = objs[a.face].mesh.position; o.mesh.rotation.y = Math.atan2(tp.x - o.mesh.position.x, tp.z - o.mesh.position.z); }
    if (a.lookCam) o.mesh.rotation.y = Math.atan2(pos.x - o.mesh.position.x, pos.z - o.mesh.position.z);
    const ex = track(a.expr, t);
    const f = o.mesh.userData.face;
    if (ex && f && f.userData.ex !== ex[0]) { f.material.map = faceTex(ex[0]); f.material.needsUpdate = true; f.userData.ex = ex[0]; }
    if (o.mesh.userData.legs) {
      const keys = a.act || [[0, 'idle']]; let ai = 0; for (let i = 0; i < keys.length; i++) if (keys[i][0] <= t) ai = i;
      actPose(o, keys[ai][1], t, keys[ai][0]);
    }
    if (a.spin) o.mesh.rotation.x = track(a.spin, t)[0] * Math.PI / 180;
  }
  composer.render();
  o2.imageSmoothingEnabled = true; o2.imageSmoothingQuality = 'high';
  o2.drawImage(renderer.domElement, 0, 0, W, H);
  // viền tối nhẹ (vignette) cho cảm giác điện ảnh
  const g = o2.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.45, W / 2, H / 2, Math.max(W, H) * 0.75);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0.28)'); o2.fillStyle = g; o2.fillRect(0, 0, W, H);
  const cap = (film.captions || []).find((q) => t >= q[0] && t < q[1]);
  if (cap) drawCaption(cap[2]);
}
export function grab(type = 'image/jpeg', q = 0.93) { return out2d.toDataURL(type, q).split(',')[1]; }

window.ENGINE = { build, frame, grab, ready: true };
