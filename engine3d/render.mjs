// node render.mjs film.json out.mp4 [--from N --to M --stills dir]
// Dựng phim 3D: mở engine trong Chromium (WebGL phần mềm SwiftShader), chụp từng khung, đẩy vào ffmpeg.
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const film = JSON.parse(fs.readFileSync(args[0], 'utf8'));
const out = args[1];
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const FPS = film.fps || 30;
const total = Math.max(...film.shots.map((s) => s.t1));
const f0 = +opt('--from', 0), f1 = +opt('--to', Math.round(total * FPS));
const stills = opt('--stills', null);
const scale = +opt('--scale', 1);
const W = Math.round((film.width || 1080) * scale), H = Math.round((film.height || 1920) * scale);

const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  const type = p.endsWith('.js') || p.endsWith('.mjs') ? 'text/javascript' : p.endsWith('.html') ? 'text/html' : 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': type }); fs.createReadStream(p).pipe(res);
}).listen(0);
const port = server.address().port;

const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on('console', (m) => { if (m.type() === 'error') console.log('[page]', m.text()); });
page.on('pageerror', (e) => console.log('[page error]', e.message));
await page.addInitScript(([w, h]) => { window.FRAME_W = w; window.FRAME_H = h; }, [W, H]);
await page.goto(`http://127.0.0.1:${port}/index.html`);
await page.waitForFunction(() => window.ENGINE && window.ENGINE.ready, null, { timeout: 60000 });
await page.evaluate((f) => { window.FILM = f; window.ENGINE.build(f.world); }, film);

async function grab(t) {
  const b64 = await page.evaluate((args) => { window.ENGINE.frame(window.FILM, args[0]); return window.ENGINE.grab(args[1]); }, [t, stills ? 'image/png' : 'image/jpeg']);
  return Buffer.from(b64, 'base64');
}

if (stills) {
  fs.mkdirSync(stills, { recursive: true });
  for (const [i, s] of film.shots.entries()) {
    fs.writeFileSync(path.join(stills, `shot_${String(i + 1).padStart(2, '0')}.png`), await grab((s.t0 + s.t1) / 2));
  }
} else {
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-vf', scale !== 1 ? `scale=${film.width || 1080}:${film.height || 1920}:flags=lanczos` : 'null',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = f0; f < f1; f++) {
    const buf = await grab(f / FPS);
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
    if ((f - f0) % 30 === 0) console.log(`[3d] khung ${f}/${f1} (${((Date.now() - t0) / 1000 / Math.max(1, f - f0)).toFixed(2)} s/khung)`);
  }
  ff.stdin.end();
  await new Promise((r) => ff.on('close', r));
}
await browser.close();
server.close();
