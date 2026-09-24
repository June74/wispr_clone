import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// Local-only preview, limited to the public demo assets.
const root = path.dirname(fileURLToPath(import.meta.url));
const publicFiles = new Set(['index_codex.html', 'styles_codex.css', 'app_codex.js', 'assets_codex/geist_codex.ttf', 'assets_codex/OFL_codex.txt']);
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.ttf': 'font/ttf', '.txt': 'text/plain; charset=utf-8' };
const port = Number(process.env.WISPR_DEMO_PORT || 8765);
http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const filename = pathname === '/' ? 'index_codex.html' : pathname.slice(1);
  if (!publicFiles.has(filename)) { res.writeHead(404); res.end('Not found'); return; }
  try {
    const body = await readFile(path.join(root, filename));
    res.writeHead(200, { 'Content-Type': types[path.extname(filename)], 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    res.end(body);
  } catch { res.writeHead(404); res.end('Not found'); }
}).listen(port, '127.0.0.1', () => console.log(`Wispr demo: http://127.0.0.1:${port}/index_codex.html`));
