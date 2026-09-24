import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const allowed=new Set(['pillars_codex.html','pillars_codex.js','pillars_codex.css','waveforms_codex.html','waveforms_codex.css','waveforms_codex.js','styles_codex.css','assets_codex/geist_codex.ttf']);
const mime={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.ttf':'font/ttf'};
const port=Number(process.env.WISPR_WAVEFORM_PORT||8766);
http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');const name=url.pathname==='/'?'waveforms_codex.html':url.pathname.slice(1);
  if(!allowed.has(name)){res.writeHead(404);res.end('Not found');return;}
  try{const body=await readFile(path.join(root,name));res.writeHead(200,{'Content-Type':mime[path.extname(name)],'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(body);}catch{res.writeHead(404);res.end('Not found');}
}).listen(port,'127.0.0.1',()=>console.log(`Waveform comparison: http://127.0.0.1:${port}/waveforms_codex.html`));
