#!/usr/bin/env node
/**
 * Rewrite a Mermaid-produced SVG into a form OmniGraffle imports faithfully.
 *
 *   node og_fix_svg.mjs FILE.svg [FILE.svg ...]        (edits in place)
 *
 * Each transform below exists because of a specific, observed OmniGraffle
 * importer limitation. Rendering in a browser is unaffected by any of them.
 *
 *   1. <line> -> <path>
 *      OmniGraffle mangles <line>, and <line> has no getTotalLength(), which
 *      step 4 needs. Paths import correctly.
 *
 *   2. One <text> element per visual row
 *      OmniGraffle merges sibling <tspan>s into a single left-aligned
 *      paragraph and ignores per-tspan x / text-anchor, so multi-line labels
 *      collapse and stop being centred in their shape. Separate <text>
 *      elements cannot be merged. Each is anchored at its measured left edge,
 *      which is correct whether or not text-anchor is honoured.
 *
 *   3. Drop zero-area rects
 *      Mermaid emits empty placeholder rects. Invisible in a browser;
 *      OmniGraffle draws them as filled boxes.
 *
 *   4. Materialise arrowheads, delete <marker> defs
 *      OmniGraffle does not apply marker-end/marker-start to paths, and it
 *      renders the <marker> definitions themselves as real objects dumped at
 *      the origin. So arrowheads are lost *and* junk is added. Replacing them
 *      with real <polygon>s fixes both, and looks identical in a browser.
 *
 *   5. Inline computed styles, converting rgba() -> rgb() + *-opacity
 *      OmniGraffle ignores the <style> block, and cannot parse rgba() (not
 *      valid SVG 1.1 paint) — it falls back to black.
 *
 *   6. Strip the now-redundant <style> block.
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
  try {
    puppeteer = createRequire(import.meta.url)('puppeteer');
  } catch {
    console.error(`error: puppeteer not found. Expected it under ${toolchain}.\n`
      + 'Run render_mermaid.sh once to provision the toolchain, or set OG_GEN_TOOLCHAIN.');
    process.exit(1);
  }
}

const files = process.argv.slice(2);
if (!files.length) {
  console.error('usage: og_fix_svg.mjs FILE.svg [FILE.svg ...]');
  process.exit(2);
}

const PROPS = ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray',
  'stroke-opacity', 'opacity', 'font-family', 'font-size', 'font-weight', 'font-style'];

const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
const page = await browser.newPage();

for (const file of files) {
  const svg = fs.readFileSync(file, 'utf8');
  await page.setContent(`<!doctype html><body style="margin:0">${svg}</body>`, { waitUntil: 'load' });

  const out = await page.evaluate((PROPS) => {
    const NS = 'http://www.w3.org/2000/svg';
    const root = document.querySelector('svg');
    const stat = { lines: 0, rows: 0, rects: 0, heads: 0, markers: 0, rgba: 0 };

    // 1. <line> -> <path>
    for (const el of [...root.querySelectorAll('line')]) {
      const p = document.createElementNS(NS, 'path');
      for (const a of el.attributes) {
        if (!['x1', 'y1', 'x2', 'y2'].includes(a.name)) p.setAttribute(a.name, a.value);
      }
      p.setAttribute('d', `M ${el.getAttribute('x1')},${el.getAttribute('y1')}`
        + ` L ${el.getAttribute('x2')},${el.getAttribute('y2')}`);
      el.replaceWith(p);
      stat.lines++;
    }

    // 2. one <text> per visual row, anchored at that row's own left edge
    for (const t of [...root.querySelectorAll('text')]) {
      const outers = [...t.children].filter((c) => c.tagName.toLowerCase() === 'tspan');
      const sources = outers.length ? outers : [t];
      const rows = [];
      for (const o of sources) {
        if (!o.textContent) continue;
        let bb, base;
        try { bb = o.getBBox(); base = o.getStartPositionOfChar(0).y; } catch { continue; }
        const cs = getComputedStyle(o);
        const st = {};
        for (const p of PROPS) st[p] = cs.getPropertyValue(p);
        rows.push({ txt: o.textContent, x: bb.x, y: base, st });
      }
      if (!rows.length) { t.remove(); continue; }
      const parent = t.parentNode;
      for (const r of rows) {
        const nt = document.createElementNS(NS, 'text');
        nt.setAttribute('x', r.x.toFixed(3));
        nt.setAttribute('y', r.y.toFixed(3));
        nt.setAttribute('text-anchor', 'start');
        nt.style.setProperty('text-anchor', 'start');
        nt.style.setProperty('dominant-baseline', 'auto');
        for (const p of PROPS) if (r.st[p]) nt.style.setProperty(p, r.st[p]);
        nt.textContent = r.txt;
        parent.insertBefore(nt, t);
        stat.rows++;
      }
      t.remove();
    }

    // 3. drop zero-area rects
    for (const r of [...root.querySelectorAll('rect')]) {
      let bb; try { bb = r.getBBox(); } catch { continue; }
      if (bb.width < 1 || bb.height < 1) { r.remove(); stat.rects++; }
    }

    // 4. materialise arrowheads, then delete all marker defs
    const LEN = 11, HALF = 4.2;
    const head = (tip, dir, color) => {
      const n = Math.hypot(dir.x, dir.y) || 1;
      const ux = dir.x / n, uy = dir.y / n;
      const bx = tip.x - ux * LEN, by = tip.y - uy * LEN;
      const px = -uy * HALF, py = ux * HALF;
      const poly = document.createElementNS(NS, 'polygon');
      poly.setAttribute('points',
        `${tip.x.toFixed(2)},${tip.y.toFixed(2)} `
        + `${(bx + px).toFixed(2)},${(by + py).toFixed(2)} `
        + `${(bx - px).toFixed(2)},${(by - py).toFixed(2)}`);
      poly.setAttribute('style', `fill:${color};stroke:none`);
      return poly;
    };
    for (const el of [...root.querySelectorAll('[marker-end],[marker-start]')]) {
      if (typeof el.getTotalLength !== 'function') continue;
      const L = el.getTotalLength();
      if (!(L > 2)) { el.removeAttribute('marker-end'); el.removeAttribute('marker-start'); continue; }
      const cs = getComputedStyle(el);
      const color = cs.stroke && cs.stroke !== 'none' ? cs.stroke : 'rgb(51,51,51)';
      if (el.getAttribute('marker-end')) {
        const tip = el.getPointAtLength(L), pre = el.getPointAtLength(L - 1.5);
        el.parentNode.appendChild(head(tip, { x: tip.x - pre.x, y: tip.y - pre.y }, color));
        stat.heads++;
      }
      if (el.getAttribute('marker-start')) {
        const tip = el.getPointAtLength(0), post = el.getPointAtLength(1.5);
        el.parentNode.appendChild(head(tip, { x: tip.x - post.x, y: tip.y - post.y }, color));
        stat.heads++;
      }
      el.removeAttribute('marker-end');
      el.removeAttribute('marker-start');
    }
    for (const m of [...root.querySelectorAll('marker')]) { m.remove(); stat.markers++; }

    // 5. inline computed styles, rgba() -> rgb() + *-opacity
    const setProp = (el, prop, val) => {
      const m = /^rgba\(\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\s*\)$/.exec(val);
      if (!m) { el.style.setProperty(prop, val); return; }
      el.style.setProperty(prop, `rgb(${m[1]}, ${m[2]}, ${m[3]})`);
      if (prop === 'fill' || prop === 'stroke') {
        const cur = parseFloat(getComputedStyle(el).getPropertyValue(prop + '-opacity')) || 1;
        el.style.setProperty(prop + '-opacity', String(cur * parseFloat(m[4])));
      }
      stat.rgba++;
    };
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'style') continue;
      const cs = getComputedStyle(el);
      for (const p of PROPS) { const v = cs.getPropertyValue(p); if (v) setProp(el, p, v); }
    }

    // 6. drop the now-redundant <style> block and any emptied <defs>
    for (const s of [...root.querySelectorAll('style')]) s.remove();
    for (const d of [...root.querySelectorAll('defs')]) if (!d.children.length) d.remove();

    return { stat, html: root.outerHTML };
  }, PROPS);

  fs.writeFileSync(file, out.html);
  const s = out.stat;
  console.log(`${file}: lines->paths=${s.lines} textRows=${s.rows} `
    + `rectsDropped=${s.rects} arrowheads=${s.heads} markersRemoved=${s.markers} rgbaFixed=${s.rgba}`);
}

await browser.close();
