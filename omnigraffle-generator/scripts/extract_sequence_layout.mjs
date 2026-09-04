#!/usr/bin/env node
/**
 * Extract Mermaid *sequence diagram* layout as JSON.
 *
 *   node extract_sequence_layout.mjs IN.svg > layout.json
 *
 * Mermaid's sequence output is richer than its flowchart output: messages carry
 * data-from / data-to naming the participants directly, and lifelines carry
 * data-id, so real OmniGraffle connections can be reconstructed without any
 * geometric guessing.
 *
 * Input must be rendered with htmlLabels:false, BEFORE og_fix_svg.mjs.
 */
import { createRequire } from 'module';
import fs from 'fs';

const home = process.env.HOME || '';
const toolchain = process.env.OG_GEN_TOOLCHAIN
  || `${process.env.XDG_CACHE_HOME || home + '/.cache'}/omnigraffle-generator/toolchain`;
let puppeteer;
try {
  puppeteer = createRequire(toolchain + '/package.json')('puppeteer');
} catch {
  puppeteer = createRequire(import.meta.url)('puppeteer');
}

const input = process.argv[2];
if (!input) {
  console.error('usage: extract_sequence_layout.mjs IN.svg > layout.json');
  process.exit(2);
}

const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
const page = await browser.newPage();
await page.setContent(`<!doctype html><body style="margin:0">${fs.readFileSync(input, 'utf8')}</body>`,
  { waitUntil: 'load' });

const layout = await page.evaluate(() => {
  const root = document.querySelector('svg');
  const vb = root.getAttribute('viewBox').split(/\s+/).map(Number);
  const rootCTM = root.getScreenCTM();
  const abs = (el) => {
    const b = el.getBBox();
    const m = rootCTM.inverse().multiply(el.getScreenCTM());
    return { x: b.x * m.a + b.y * m.c + m.e, y: b.x * m.b + b.y * m.d + m.f,
             w: b.width * m.a, h: b.height * m.d };
  };
  const num = (el, n) => parseFloat(el.getAttribute(n));
  const textRows = (el) => {
    const outers = [...el.children].filter((c) => c.tagName.toLowerCase() === 'tspan');
    const src = outers.length ? outers : [el];
    return src.map((o) => o.textContent.trim()).filter(Boolean);
  };
  const centre = (el) => { const b = abs(el); return { cx: b.x + b.w / 2, cy: b.y + b.h / 2 }; };

  // participant boxes, top and bottom rows
  const actors = [];
  for (const r of root.querySelectorAll('rect.actor')) {
    const b = abs(r);
    actors.push({
      name: r.getAttribute('name'),
      which: (r.getAttribute('class') || '').includes('actor-bottom') ? 'bottom' : 'top',
      x: b.x, y: b.y, w: b.w, h: b.h, label: '',
    });
  }
  // actor captions are separate <text class="actor">; attach by containment
  for (const t of root.querySelectorAll('text.actor')) {
    const c = centre(t);
    const rows = textRows(t);
    let best = null;
    for (const a of actors) {
      if (c.cx >= a.x && c.cx <= a.x + a.w && c.cy >= a.y && c.cy <= a.y + a.h) best = a;
    }
    if (best) best.label = best.label ? best.label + '\n' + rows.join('\n') : rows.join('\n');
  }

  const lifelines = [];
  for (const l of root.querySelectorAll('line.actor-line, path.actor-line')) {
    const id = l.getAttribute('data-id') || l.getAttribute('name');
    if (l.tagName.toLowerCase() === 'line') {
      lifelines.push({ id, x1: num(l, 'x1'), y1: num(l, 'y1'), x2: num(l, 'x2'), y2: num(l, 'y2') });
    } else {
      const L = l.getTotalLength();
      const a = l.getPointAtLength(0), b = l.getPointAtLength(L);
      lifelines.push({ id, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }
  }

  const messages = [];
  for (const l of root.querySelectorAll('[class*="messageLine"]')) {
    const cls = l.getAttribute('class') || '';
    const rec = { from: l.getAttribute('data-from'), to: l.getAttribute('data-to'),
                  dashed: cls.includes('messageLine1'),
                  arrow: !!l.getAttribute('marker-end') };
    if (l.tagName.toLowerCase() === 'line') {
      Object.assign(rec, { x1: num(l, 'x1'), y1: num(l, 'y1'), x2: num(l, 'x2'), y2: num(l, 'y2') });
    } else {
      const L = l.getTotalLength();
      const a = l.getPointAtLength(0), b = l.getPointAtLength(L);
      Object.assign(rec, { x1: a.x, y1: a.y, x2: b.x, y2: b.y, curved: true });
    }
    messages.push(rec);
  }

  const notes = [];
  for (const r of root.querySelectorAll('rect.note')) {
    const b = abs(r);
    notes.push({ x: b.x, y: b.y, w: b.w, h: b.h, text: '' });
  }
  for (const t of root.querySelectorAll('text.noteText')) {
    const c = centre(t);
    const rows = textRows(t);
    for (const n of notes) {
      if (c.cx >= n.x && c.cx <= n.x + n.w && c.cy >= n.y - 4 && c.cy <= n.y + n.h + 4) {
        n.text = n.text ? n.text + '\n' + rows.join('\n') : rows.join('\n');
        break;
      }
    }
  }

  const activations = [];
  for (const r of root.querySelectorAll('[class*="activation"]')) {
    const b = abs(r);
    activations.push({ x: b.x, y: b.y, w: b.w, h: b.h });
  }

  const labels = [];
  for (const t of root.querySelectorAll('text.messageText')) {
    const b = abs(t);
    labels.push({ x: b.x, y: b.y, w: b.w, h: b.h, text: textRows(t).join('\n') });
  }

  const seqNumbers = [];
  for (const t of root.querySelectorAll('text.sequenceNumber')) {
    const b = abs(t);
    seqNumbers.push({ x: b.x, y: b.y, w: b.w, h: b.h, text: t.textContent.trim() });
  }

  return { viewBox: vb, actors, lifelines, messages, notes, activations, labels, seqNumbers };
});

await browser.close();
process.stdout.write(JSON.stringify(layout, null, 1));
