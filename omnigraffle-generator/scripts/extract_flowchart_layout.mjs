#!/usr/bin/env node
/**
 * Extract flowchart layout (nodes, edges, edge labels) from a Mermaid SVG as JSON.
 *
 *   node extract_flowchart_layout.mjs IN.svg > layout.json
 *
 * Geometry comes from getBBox()/getCTM() in a real browser rather than from
 * attributes, so every Mermaid node shape works — rectangles, cylinders,
 * subroutines, stadiums — not just <rect>.
 *
 * Edge geometry comes from Mermaid's own `data-points` (base64 JSON), which is
 * the routed polyline, and `data-id` ("L_<src>_<tgt>_<n>") gives the endpoints
 * needed to build real OmniGraffle connections.
 *
 * Input must be a flowchart rendered with htmlLabels:false, BEFORE og_fix_svg.mjs.
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
  console.error('usage: extract_flowchart_layout.mjs IN.svg > layout.json');
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

  // absolute bbox in the SVG's own user space
  const abs = (el) => {
    const b = el.getBBox();
    const m = rootCTM.inverse().multiply(el.getScreenCTM());
    return { x: b.x * m.a + b.y * m.c + m.e, y: b.x * m.b + b.y * m.d + m.f,
             w: b.width * m.a, h: b.height * m.d };
  };
  const textOf = (el) => {
    const rows = [];
    for (const t of el.querySelectorAll('text')) {
      const outers = [...t.children].filter((c) => c.tagName.toLowerCase() === 'tspan');
      const src = outers.length ? outers : [t];
      for (const o of src) if (o.textContent.trim()) rows.push(o.textContent.trim());
    }
    return rows.join('\n');
  };


  // Measure text the way OmniGraffle will render it. Our RTF asks for Helvetica
  // \fs24, which OmniGraffle lays out at 12 canvas units per em -- not the 16px
  // the SVG uses. Calibrated against OmniGraffle's own auto-fit: measuring at
  // 12px Helvetica reproduces its widths to within 0.5%, and a line box is
  // exactly 14 units tall once Text.Pad/VerticalPad are zeroed.
  const _mc = document.createElement('canvas').getContext('2d');
  _mc.font = '12px Helvetica';
  const measure = (txt) => {
    const rows = (txt || '').split('\n').filter((r) => r.length);
    if (!rows.length) return { w: 0, h: 0 };
    return { w: Math.max(...rows.map((r) => _mc.measureText(r).width)), h: 14 * rows.length };
  };

  const nodes = [];
  for (const g of root.querySelectorAll('g.node')) {
    const shape = g.querySelector(':scope > rect, :scope > path, :scope > polygon, :scope > circle, :scope > ellipse');
    if (!shape) continue;
    const b = abs(shape);
    const label = g.querySelector(':scope > g.label');
    let key = (g.id || '').replace(/^.*?flowchart-/, '').replace(/-\d+$/, '');
    // measure the rendered label so the shape can be sized to its text rather
    // than to Mermaid's generously padded container
    const m = measure(textOf(label || g));
    nodes.push({ key, x: b.x, y: b.y, w: b.w, h: b.h, textW: m.w, textH: m.h,
                 label: textOf(label || g), shape: shape.tagName.toLowerCase() });
  }

  // subgraph containers
  const clusters = [];
  for (const g of root.querySelectorAll('g.cluster')) {
    const box = g.querySelector(':scope > rect, :scope > path, :scope > polygon');
    if (!box) continue;
    const b = abs(box);
    const lbl = g.querySelector(':scope > g.cluster-label');
    clusters.push({ key: (g.id || '').replace(/^.*?-/, ''), x: b.x, y: b.y, w: b.w, h: b.h,
                    label: lbl ? textOf(lbl) : '' });
  }

  const edges = [];
  for (const p of root.querySelectorAll('path.flowchart-link')) {
    const did = p.getAttribute('data-id');
    const dp = p.getAttribute('data-points');
    let pts = null;
    if (dp) {
      try { pts = JSON.parse(atob(dp)).map((q) => [q.x, q.y]); } catch { pts = null; }
    }
    if (!pts || pts.length < 2) {
      // fall back to sampling the rendered path
      const L = p.getTotalLength();
      pts = [];
      const N = Math.max(2, Math.min(24, Math.round(L / 25)));
      for (let i = 0; i <= N; i++) {
        const q = p.getPointAtLength((L * i) / N);
        pts.push([q.x, q.y]);
      }
    }
    edges.push({ id: did, points: pts,
                 dashed: (p.getAttribute('class') || '').includes('edge-pattern-dotted') });
  }

  const edgeLabels = [];
  for (const g of root.querySelectorAll('g.edgeLabel')) {
    const txt = textOf(g);
    if (!txt) continue;
    const b = abs(g);
    const m = measure(txt);
    edgeLabels.push({ x: b.x, y: b.y, w: b.w, h: b.h, textW: m.w, textH: m.h, label: txt });
  }

  return { viewBox: vb, nodes, clusters, edges, edgeLabels };
});

await browser.close();
process.stdout.write(JSON.stringify(layout, null, 1));
