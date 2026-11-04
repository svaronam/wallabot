/* Wallabot · Análisis
 * Todo el cruce de datos ocurre aquí, en el móvil: el bot manda los anuncios del periodo
 * una vez y cada filtro o selección recalcula todos los gráficos al instante.
 * Gráficos en SVG propio (sin librerías) para que funcione sin internet dentro de Tailscale.
 */
(function () {
  'use strict';
  const DAY = 86400;
  const DOW = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
  const DOW_FULL = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
  const STATUS = { active: 'En venta', reserved: 'Reservado', sold: 'Vendido', gone: 'Retirado' };
  const NS = 'http://www.w3.org/2000/svg';

  // ------------------------------------------------------------------ estado
  let API = null, ROOT = null, DATA = null, ITEMS = [], SNAMES = {}, BUCKETS = null;
  const UI = {
    days: 90, xdim: 'priceRange', metric: 'medDays', split: '', sort: 'natural',
    heat: 'sellRate', time: 'counts', tableSort: { k: 'pub', d: -1 }, tableN: 25, text: '',
  };
  const SEL = {};               // dimensión -> Set de claves seleccionadas (filtros cruzados)
  let pickedPoint = null;

  // ------------------------------------------------------------------ utilidades
  const fmtN = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
  const eur = v => v == null ? '–' : new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: Math.abs(v) < 100 && v % 1 ? 2 : 0 }).format(v);
  const pct = v => v == null ? '–' : (Math.round(v * 10) / 10).toString().replace('.', ',') + ' %';
  const dys = v => v == null ? '–' : v === 0 ? '0' : (v < 1 ? Math.round(v * 24) + ' h' : (Math.round(v * 10) / 10).toString().replace('.', ',') + ' d');
  const int = v => v == null ? '–' : fmtN.format(v);
  const median = xs => { const a = xs.filter(x => x != null && !isNaN(x)).sort((p, q) => p - q); if (!a.length) return null; const m = a.length >> 1; return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2; };
  const quant = (xs, p) => { const a = xs.filter(x => x != null).sort((x, y) => x - y); if (!a.length) return null; return a[Math.min(a.length - 1, Math.max(0, Math.round((a.length - 1) * p)))]; };
  const avg = xs => { const a = xs.filter(x => x != null); return a.length ? a.reduce((s, x) => s + x, 0) / a.length : null; };
  const el = (tag, attrs, kids) => { const e = document.createElement(tag); for (const k in attrs || {}) { if (k === 'text') e.textContent = attrs[k]; else if (k === 'cls') e.className = attrs[k]; else if (k.startsWith('on')) e.addEventListener(k.slice(2), attrs[k]); else e.setAttribute(k, attrs[k]); } (kids || []).forEach(c => c && e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c)); return e; };
  const sv = (tag, attrs, kids) => { const e = document.createElementNS(NS, tag); for (const k in attrs || {}) e.setAttribute(k, attrs[k]); (kids || []).forEach(c => c && e.appendChild(c)); return e; };
  const svText = (attrs, txt) => { const t = sv('text', attrs); t.textContent = txt; return t; };
  const dayKey = ts => { const d = new Date(ts * 1000); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
  const shortDay = k => { const p = k.split('-'); return p[2] + '/' + p[1]; };
  function niceStep(span, target) {
    const raw = span / Math.max(1, target), mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), n = raw / mag;
    return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
  }
  function ticks(max, n = 4) { if (!max || max <= 0) return [0]; const st = niceStep(max, n); const out = []; for (let v = 0; v <= max * 1.0001 + st * 0.001; v += st) out.push(+v.toFixed(6)); if (out[out.length - 1] < max) out.push(+(out[out.length - 1] + st).toFixed(6)); return out; }
  // barra horizontal: esquina redondeada solo en el extremo del dato
  function hbarPath(x, y, w, h) { const r = Math.min(4, w, h / 2); if (w <= 0) return ''; return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(w - r)}z`; }
  function vbarPath(x, y0, w, h) { const r = Math.min(4, w / 2, h); if (h <= 0) return ''; return `M${x},${y0}v${-(h - r)}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${h - r}z`; }
  const SERIES = n => `var(--s${n + 1})`;

  // ------------------------------------------------------------------ dimensiones y métricas
  function bucketOf(p) {
    if (p == null || !BUCKETS) return 'na';
    if (p < BUCKETS.lo) return 'lt';
    if (p >= BUCKETS.hi) return 'gt';
    return String(Math.floor((p - BUCKETS.lo) / BUCKETS.step));
  }
  function bucketName(k) {
    if (!BUCKETS) return k;
    if (k === 'na') return 'Sin precio';
    if (k === 'lt') return '< ' + eur(BUCKETS.lo);
    if (k === 'gt') return '≥ ' + eur(BUCKETS.hi);
    const a = BUCKETS.lo + (+k) * BUCKETS.step; return eur(a) + '–' + eur(a + BUCKETS.step);
  }
  function bucketOrder() {
    if (!BUCKETS) return [];
    const o = ['lt']; for (let i = 0; i < BUCKETS.n; i++) o.push(String(i)); o.push('gt'); return o;
  }
  const SPEED = [['h24', '< 1 día'], ['d3', '1–3 días'], ['d7', '3–7 días'], ['d14', '7–14 días'], ['d30', '14–30 días'], ['more', '> 30 días'], ['unsold', 'Sin vender']];
  const speedKey = it => !it.sold || it.days == null ? 'unsold' : it.days < 1 ? 'h24' : it.days < 3 ? 'd3' : it.days < 7 ? 'd7' : it.days < 14 ? 'd14' : it.days < 30 ? 'd30' : 'more';
  const DISC = [['none', 'Sin rebaja'], ['d10', 'Hasta 10 %'], ['d20', '10–20 %'], ['d30', '20–30 %'], ['more', '> 30 %']];
  const discKey = it => !it.disc ? 'none' : it.disc <= 10 ? 'd10' : it.disc <= 20 ? 'd20' : it.disc <= 30 ? 'd30' : 'more';

  const DIMS = {
    priceRange: { label: 'Rango de precio', keys: it => [bucketOf(it.price)], name: bucketName, order: bucketOrder },
    search: { label: 'Búsqueda', keys: it => it.searches.length ? it.searches.map(String) : ['0'], name: k => SNAMES[k] || 'Sin búsqueda', order: null },
    status: { label: 'Estado', keys: it => [it.status], name: k => STATUS[k] || k, order: () => ['active', 'reserved', 'sold', 'gone'] },
    city: { label: 'Ciudad', keys: it => [it.city || '¿?'], name: k => k, order: null, top: 15 },
    shipping: { label: 'Envío', keys: it => [it.shipping ? '1' : '0'], name: k => k === '1' ? 'Con envío' : 'Sin envío', order: () => ['1', '0'] },
    dow: { label: 'Día de publicación', keys: it => [String(it.dow)], name: k => DOW[+k], order: () => ['0', '1', '2', '3', '4', '5', '6'] },
    hour: { label: 'Hora de publicación', keys: it => [String(it.hour)], name: k => String(k).padStart(2, '0') + ' h', order: () => Array.from({ length: 24 }, (_, i) => String(i)) },
    drops: { label: 'Bajadas de precio', keys: it => [it.drops >= 2 ? '2' : String(it.drops)], name: k => k === '0' ? 'Ninguna' : k === '1' ? '1 bajada' : '2 o más', order: () => ['0', '1', '2'] },
    discount: { label: 'Rebaja sobre el precio inicial', keys: it => [discKey(it)], name: k => (DISC.find(d => d[0] === k) || [k, k])[1], order: () => DISC.map(d => d[0]) },
    speed: { label: 'Tiempo hasta vender', keys: it => [speedKey(it)], name: k => (SPEED.find(d => d[0] === k) || [k, k])[1], order: () => SPEED.map(d => d[0]) },
  };
  const isSold = it => it.sold;
  const METRICS = {
    count: { label: 'Nº de anuncios', f: a => a.length, fmt: int },
    sold: { label: 'Nº de vendidos', f: a => a.filter(isSold).length, fmt: int },
    sellRate: { label: '% que se vende', f: a => a.length ? a.filter(isSold).length / a.length * 100 : null, fmt: pct, rate: true },
    fast: { label: '% vendido en < 3 días', f: a => a.length ? a.filter(i => i.sold && i.days != null && i.days < 3).length / a.length * 100 : null, fmt: pct, rate: true },
    medDays: { label: 'Días en venderse', f: a => median(a.filter(isSold).map(i => i.days)), fmt: dys, soldOnly: true },
    medSold: { label: 'Precio de venta', f: a => median(a.filter(isSold).map(i => i.price)), fmt: eur, soldOnly: true },
    medPrice: { label: 'Precio pedido', f: a => median(a.map(i => i.price)), fmt: eur },
    discount: { label: 'Rebaja al vender', f: a => avg(a.filter(isSold).map(i => i.disc || 0)), fmt: pct, soldOnly: true },
    volume: { label: '€ movidos en ventas', f: a => a.filter(isSold).reduce((s, i) => s + (i.price || 0), 0), fmt: eur },
  };
  const sampleOf = (m, a) => METRICS[m].soldOnly ? a.filter(isSold).length : a.length;
  const MIN_N = 4; // por debajo, la barra se pinta atenuada como "pocos datos"

  // ------------------------------------------------------------------ datos
  function prepare(data) {
    DATA = data;
    SNAMES = {}; data.searches.forEach(s => SNAMES[String(s.id)] = s.name);
    const c = {}; data.cols.forEach((k, i) => c[k] = i);
    ITEMS = data.rows.map(r => {
      const it = {
        id: r[c.id], title: r[c.title] || '', price: r[c.price], first: r[c.first_price], status: r[c.status],
        firstSeen: r[c.first_seen], created: r[c.created_ts], changed: r[c.changed], city: r[c.city],
        shipping: !!r[c.shipping], followed: !!r[c.followed], slug: r[c.slug], image: r[c.image],
        drops: r[c.drops] || 0, searches: r[c.searches] || [],
      };
      it.pub = it.created && it.firstSeen ? Math.min(it.created, it.firstSeen) : (it.created || it.firstSeen);
      it.sold = it.status === 'sold' || it.status === 'gone';
      it.days = it.sold && it.changed && it.pub ? Math.max(0, (it.changed - it.pub) / DAY) : null;
      it.disc = it.first && it.price != null && it.first > it.price ? (it.first - it.price) / it.first * 100 : 0;
      const d = new Date((it.pub || data.now) * 1000);
      it.dow = (d.getDay() + 6) % 7; it.hour = d.getHours();
      it.pubDay = it.pub ? dayKey(it.pub) : null;
      it.soldDay = it.sold && it.changed ? dayKey(it.changed) : null;
      it.lc = it.title.toLowerCase();
      return it;
    });
    // tramos de precio estables (no cambian al filtrar, así la selección no se mueve)
    const prices = ITEMS.map(i => i.price).filter(p => p != null && p > 0);
    if (prices.length >= 3) {
      const lo0 = quant(prices, 0.03), hi0 = quant(prices, 0.97);
      const step = niceStep(Math.max(1, hi0 - lo0), 8);
      const lo = Math.floor(lo0 / step) * step, hi = Math.ceil((hi0 + 0.0001) / step) * step;
      BUCKETS = { lo, hi, step, n: Math.max(1, Math.round((hi - lo) / step)) };
    } else BUCKETS = null;
  }

  function passes(it, except) {
    if (UI.text) { for (const w of UI.text) if (!it.lc.includes(w)) return false; }
    for (const d in SEL) {
      if (d === except || !SEL[d].size) continue;
      if (Array.isArray(except) && except.includes(d)) continue;
      if (!DIMS[d].keys(it).some(k => SEL[d].has(k))) return false;
    }
    return true;
  }
  const filtered = except => ITEMS.filter(it => passes(it, except));

  function groupBy(items, dim) {
    const g = new Map();
    for (const it of items) for (const k of DIMS[dim].keys(it)) { if (!g.has(k)) g.set(k, []); g.get(k).push(it); }
    return g;
  }

  function toggle(dim, key, solo) {
    if (!SEL[dim]) SEL[dim] = new Set();
    const s = SEL[dim];
    if (solo) { const had = s.has(key) && s.size === 1; s.clear(); if (!had) s.add(key); }
    else if (s.has(key)) s.delete(key); else s.add(key);
    if (!s.size) delete SEL[dim];
    pickedPoint = null;
    draw();
  }

  // ------------------------------------------------------------------ tooltip (uno para todos los gráficos)
  let TIP = null;
  function tipShow(evt, rows, head) {
    if (!TIP) return;
    TIP.textContent = '';
    if (head) TIP.appendChild(el('div', { cls: 'an-tip-h', text: head }));
    rows.forEach(r => {
      const line = el('div', { cls: 'an-tip-r' });
      if (r.color) line.appendChild(el('i', { style: `background:${r.color}` }));
      line.appendChild(el('b', { text: r.value }));
      if (r.label) line.appendChild(el('span', { text: r.label }));
      TIP.appendChild(line);
    });
    TIP.style.display = 'block';
    const pad = 12, w = TIP.offsetWidth, h = TIP.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > window.innerHeight - 70) y = evt.clientY - h - pad;
    TIP.style.left = Math.max(8, x) + 'px'; TIP.style.top = Math.max(8, y) + 'px';
  }
  const tipHide = () => { if (TIP) TIP.style.display = 'none'; };
  function hover(node, fn) {
    node.addEventListener('pointermove', e => { const r = fn(); tipShow(e, r.rows, r.head); });
    node.addEventListener('pointerdown', e => { const r = fn(); tipShow(e, r.rows, r.head); });
    node.addEventListener('pointerleave', tipHide);
  }

  // ------------------------------------------------------------------ gráfico de barras horizontales (cruce)
  function hbars(box, rows, opt) {
    // rows: [{key, label, vals:[{v,n}]}], opt: {series:[{name,color}], fmt, dim, selected:Set|null, onClick}
    box.textContent = '';
    const W = Math.max(280, box.clientWidth || 320);
    const ns = opt.series.length;
    const barH = ns > 1 ? 9 : 14, gap = 2, rowPad = 9;
    const rowH = ns * barH + (ns - 1) * gap + rowPad * 2;
    const labW = Math.min(132, Math.round(W * 0.34)), valW = ns > 1 ? 8 : 62;
    const x0 = labW + 8, bw = W - x0 - valW;
    const max = Math.max(0, ...rows.flatMap(r => r.vals.map(v => v.v || 0)));
    const tk = ticks(max, W < 400 ? 3 : 4), tmax = tk[tk.length - 1] || 1;
    const H = rows.length * rowH + 22;
    const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'an-svg', role: 'img', 'aria-label': opt.aria || '' });
    tk.forEach(t => {
      const x = x0 + t / tmax * bw;
      svg.appendChild(sv('line', { x1: x, x2: x, y1: 0, y2: H - 18, class: 'an-grid' }));
      svg.appendChild(svText({ x, y: H - 4, class: 'an-axis', 'text-anchor': 'middle' }, opt.fmtAxis ? opt.fmtAxis(t) : opt.fmt(t)));
    });
    rows.forEach((r, i) => {
      const y = i * rowH;
      const dim = opt.selected && opt.selected.size && !opt.selected.has(r.key);
      const g = sv('g', { class: 'an-row' + (dim ? ' an-dim' : '') + (opt.onClick ? ' an-click' : ''), tabindex: 0 });
      g.appendChild(sv('rect', { x: 0, y, width: W, height: rowH, class: 'an-hit' }));
      const lab = svText({ x: labW, y: y + rowH / 2 + 4, class: 'an-lab', 'text-anchor': 'end' }, r.label.length > 22 ? r.label.slice(0, 21) + '…' : r.label);
      g.appendChild(lab);
      r.vals.forEach((v, j) => {
        const by = y + rowPad + j * (barH + gap);
        const w = v.v ? Math.max(1.5, v.v / tmax * bw) : 0;
        const low = v.n != null && v.n < MIN_N;
        if (w) g.appendChild(sv('path', { d: hbarPath(x0, by, w, barH), fill: opt.series[j].color, class: low ? 'an-low' : '' }));
        if (ns === 1) g.appendChild(svText({ x: x0 + w + 6, y: by + barH / 2 + 4, class: 'an-val' }, v.v == null ? 'sin datos' : opt.fmt(v.v) + (low ? ' ·' : '')));
      });
      hover(g, () => ({
        head: r.label,
        rows: r.vals.map((v, j) => ({ color: opt.series[j].color, value: v.v == null ? 'sin datos' : opt.fmt(v.v), label: (ns > 1 ? opt.series[j].name + ' · ' : '') + (v.n != null ? v.n + ' anuncios' + (v.n < MIN_N ? ' (pocos datos)' : '') : '') })),
      }));
      if (opt.onClick) { g.addEventListener('click', () => opt.onClick(r.key)); g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); opt.onClick(r.key); } }); }
      svg.appendChild(g);
    });
    box.appendChild(svg);
  }

  // ------------------------------------------------------------------ barras verticales (tiempo e histograma)
  function vbars(box, cols, opt) {
    // cols: [{key, label, vals:[v], tip?}], opt: {series:[{name,color}], fmt, selected, onClick, labelEvery}
    box.textContent = '';
    const W = Math.max(280, box.clientWidth || 320), H = opt.height || 190;
    const ns = opt.series.length;
    const padL = 44, padB = 24, padT = 8, x0 = padL, plotW = W - padL - 4, plotH = H - padB - padT;
    const max = Math.max(0, ...cols.flatMap(c => c.vals.map(v => v || 0)));
    const tk = ticks(max, 4), tmax = tk[tk.length - 1] || 1;
    const slot = plotW / Math.max(1, cols.length);
    const inner = Math.max(2, slot - Math.min(8, slot * 0.25));
    const bw = Math.max(1.5, (inner - (ns - 1) * 2) / ns);
    const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'an-svg', role: 'img', 'aria-label': opt.aria || '' });
    const yOf = v => padT + plotH - v / tmax * plotH;
    tk.forEach(t => {
      svg.appendChild(sv('line', { x1: x0, x2: W - 4, y1: yOf(t), y2: yOf(t), class: t === 0 ? 'an-base' : 'an-grid' }));
      svg.appendChild(svText({ x: x0 - 6, y: yOf(t) + 4, class: 'an-axis', 'text-anchor': 'end' }, opt.fmtAxis ? opt.fmtAxis(t) : opt.fmt(t)));
    });
    const every = opt.labelEvery || Math.max(1, Math.ceil(cols.length / Math.max(3, Math.floor(plotW / 46))));
    cols.forEach((c, i) => {
      const sx = x0 + i * slot, dim = opt.selected && opt.selected.size && !opt.selected.has(c.key);
      const g = sv('g', { class: 'an-col' + (dim ? ' an-dim' : '') + (opt.onClick ? ' an-click' : ''), tabindex: 0 });
      g.appendChild(sv('rect', { x: sx, y: padT, width: slot, height: plotH, class: 'an-hit' }));
      c.vals.forEach((v, j) => {
        if (!v) return;
        const h = Math.max(1.5, v / tmax * plotH);
        g.appendChild(sv('path', { d: vbarPath(sx + (slot - inner) / 2 + j * (bw + 2), padT + plotH, bw, h), fill: opt.series[j].color, class: c.low ? 'an-low' : '' }));
      });
      if (i % every === 0) svg.appendChild(svText({ x: sx + slot / 2, y: H - 7, class: 'an-axis', 'text-anchor': 'middle' }, c.label));
      hover(g, () => ({ head: c.tipHead || c.label, rows: c.tip || c.vals.map((v, j) => ({ color: opt.series[j].color, value: opt.fmt(v || 0), label: opt.series[j].name })) }));
      if (opt.onClick) g.addEventListener('click', () => opt.onClick(c.key));
      svg.appendChild(g);
    });
    box.appendChild(svg);
  }

  // ------------------------------------------------------------------ mapa de calor día × hora
  function heatmap(box, items, metric) {
    box.textContent = '';
    const W = Math.max(280, box.clientWidth || 320);
    const labW = 34, cell = (W - labW - 2) / 24, ch = Math.max(16, Math.min(26, cell * 1.15));
    const H = 7 * ch + 20;
    const grid = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => []));
    items.forEach(it => grid[it.dow][it.hour].push(it));
    const vals = grid.map(r => r.map(a => sampleOf(metric, a) >= (METRICS[metric].rate || METRICS[metric].soldOnly ? MIN_N : 1) ? METRICS[metric].f(a) : null));
    const flat = vals.flat().filter(v => v != null);
    const lo = Math.min(...flat, 0), hi = Math.max(...flat, 1);
    const selD = SEL.dow, selH = SEL.hour;
    const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'an-svg', role: 'img', 'aria-label': 'Mapa de calor por día y hora de publicación' });
    for (let d = 0; d < 7; d++) {
      svg.appendChild(svText({ x: labW - 6, y: d * ch + ch / 2 + 4, class: 'an-axis', 'text-anchor': 'end' }, DOW[d]));
      for (let h = 0; h < 24; h++) {
        const v = vals[d][h];
        const step = v == null ? 0 : 1 + Math.min(4, Math.floor((v - lo) / Math.max(1e-9, hi - lo) * 5));
        const on = (!selD || selD.has(String(d))) && (!selH || selH.has(String(h)));
        const r = sv('rect', { x: labW + h * cell + 1, y: d * ch + 1, width: Math.max(1, cell - 2), height: ch - 2, rx: 2, fill: step ? `var(--q${step})` : 'var(--chip)', class: 'an-cell an-click' + (on ? '' : ' an-dim'), tabindex: 0 });
        const a = grid[d][h];
        hover(r, () => ({ head: `${DOW[d]} · ${String(h).padStart(2, '0')}:00–${String(h).padStart(2, '0')}:59`, rows: [{ value: v == null ? 'pocos datos' : METRICS[metric].fmt(v), label: METRICS[metric].label }, { value: String(a.length), label: 'anuncios publicados' }] }));
        r.addEventListener('click', () => {
          const same = selD && selH && selD.size === 1 && selH.size === 1 && selD.has(String(d)) && selH.has(String(h));
          delete SEL.dow; delete SEL.hour;
          if (!same) { SEL.dow = new Set([String(d)]); SEL.hour = new Set([String(h)]); }
          draw();
        });
        svg.appendChild(r);
      }
    }
    [0, 6, 12, 18, 23].forEach(h => svg.appendChild(svText({ x: labW + h * cell + cell / 2, y: H - 5, class: 'an-axis', 'text-anchor': 'middle' }, h + 'h')));
    box.appendChild(svg);
    return { lo, hi };
  }

  // ------------------------------------------------------------------ dispersión precio × días
  function scatter(box, items, colorOf, onPick) {
    box.textContent = '';
    const W = Math.max(280, box.clientWidth || 320), H = 230;
    const padL = 44, padB = 26, padT = 8, padR = 8, pw = W - padL - padR, ph = H - padT - padB;
    const pts = items.filter(i => i.sold && i.days != null && i.price != null);
    const xmax = Math.max(...pts.map(p => p.price), 1), ymax = Math.max(...pts.map(p => p.days), 1);
    const xt = ticks(xmax, W < 400 ? 3 : 5), yt = ticks(ymax, 4);
    const X = v => padL + Math.min(v, xt[xt.length - 1]) / xt[xt.length - 1] * pw;
    const Y = v => padT + ph - Math.min(v, yt[yt.length - 1]) / yt[yt.length - 1] * ph;
    const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'an-svg', role: 'img', 'aria-label': 'Precio frente a días hasta vender' });
    yt.forEach(t => { svg.appendChild(sv('line', { x1: padL, x2: W - padR, y1: Y(t), y2: Y(t), class: t ? 'an-grid' : 'an-base' })); svg.appendChild(svText({ x: padL - 6, y: Y(t) + 4, class: 'an-axis', 'text-anchor': 'end' }, dys(t))); });
    xt.forEach(t => svg.appendChild(svText({ x: X(t), y: H - 8, class: 'an-axis', 'text-anchor': 'middle' }, eur(t))));
    if (!pts.length) svg.appendChild(svText({ x: W / 2, y: H / 2, class: 'an-axis', 'text-anchor': 'middle' }, 'Todavía no hay ventas con estos filtros'));
    pts.forEach(p => {
      const cx = X(p.price), cy = Y(p.days);
      const g = sv('g', { class: 'an-click', tabindex: 0 });
      g.appendChild(sv('circle', { cx, cy, r: 12, class: 'an-hit' }));
      g.appendChild(sv('circle', { cx, cy, r: pickedPoint === p.id ? 6 : 4, fill: colorOf(p), class: 'an-dot' + (pickedPoint === p.id ? ' an-picked' : '') }));
      hover(g, () => ({ head: p.title, rows: [{ value: eur(p.price), label: 'precio de venta' }, { value: dys(p.days), label: 'hasta vender' }] }));
      g.addEventListener('click', () => onPick(p));
      svg.appendChild(g);
    });
    box.appendChild(svg);
  }

  // ------------------------------------------------------------------ interfaz
  function card(title, sub, body, controls) {
    const c = el('section', { cls: 'card an-card' });
    const head = el('div', { cls: 'an-head' }, [el('div', {}, [el('h3', { text: title }), sub ? el('p', { cls: 'muted an-sub', text: sub }) : null])]);
    if (controls) head.appendChild(controls);
    c.appendChild(head); c.appendChild(body); return c;
  }
  function select(options, value, onChange, aria) {
    const s = el('select', { cls: 'an-sel', 'aria-label': aria || '' });
    options.forEach(([v, l]) => { const o = el('option', { value: v, text: l }); if (v === value) o.selected = true; s.appendChild(o); });
    s.addEventListener('change', () => onChange(s.value)); return s;
  }
  function legend(series, shape) {
    return el('div', { cls: 'an-legend' }, series.map(s => el('span', {}, [el('i', { cls: shape === 'dot' ? 'dot-key' : '', style: `background:${s.color}` }), s.name])));
  }

  const PRESETS = [
    ['¿A qué precio se vende antes?', { xdim: 'priceRange', metric: 'medDays', split: '' }],
    ['¿Qué rango de precio se vende más?', { xdim: 'priceRange', metric: 'sellRate', split: '' }],
    ['¿Qué día conviene publicar?', { xdim: 'dow', metric: 'sellRate', split: '' }],
    ['¿A qué hora conviene publicar?', { xdim: 'hour', metric: 'fast', split: '' }],
    ['¿Ayuda ofrecer envío?', { xdim: 'shipping', metric: 'sellRate', split: 'search' }],
    ['¿Bajar el precio funciona?', { xdim: 'drops', metric: 'sellRate', split: '' }],
    ['¿Dónde se vende más?', { xdim: 'city', metric: 'sold', split: '' }],
    ['Comparar búsquedas', { xdim: 'search', metric: 'medSold', split: '' }],
    ['¿Cuánto se rebaja antes de vender?', { xdim: 'search', metric: 'discount', split: '' }],
  ];

  function kpis(items) {
    const sold = items.filter(isSold), active = items.filter(i => !i.sold);
    const sp = items.filter(i => i.shipping), ns = items.filter(i => !i.shipping);
    const rate = a => a.length ? a.filter(isSold).length / a.length * 100 : null;
    const tiles = [
      [int(items.length), 'anuncios', `${int(active.length)} en venta`],
      [int(sold.length), 'vendidos', items.length ? pct(sold.length / items.length * 100) + ' del total' : ''],
      [eur(median(sold.map(i => i.price))), 'precio de venta', 'mediana'],
      [eur(median(active.map(i => i.price))), 'precio pedido', 'mediana de lo que sigue en venta'],
      [dys(median(sold.map(i => i.days))), 'hasta vender', 'mediana'],
      [eur(sold.reduce((s, i) => s + (i.price || 0), 0)), 'movidos', 'suma de ventas'],
      [pct(rate(sp)), 'se vende con envío', `${pct(rate(ns))} sin envío`],
      [pct(avg(sold.map(i => i.disc || 0))), 'rebaja media', 'de lo vendido'],
    ];
    return el('div', { cls: 'an-kpis' }, tiles.map(([v, l, s]) => el('div', { cls: 'kpi' }, [el('b', { text: v }), el('small', { text: l }), s ? el('small', { cls: 'an-kpi-s', text: s }) : null])));
  }

  function insights(items) {
    const out = [];
    const best = (dim, metric, lower) => {
      const g = groupBy(items, dim); let b = null;
      g.forEach((a, k) => { if (sampleOf(metric, a) < 6) return; const v = METRICS[metric].f(a); if (v == null) return; if (!b || (lower ? v < b.v : v > b.v)) b = { k, v, n: a.length }; });
      return b;
    };
    const p = best('priceRange', 'medDays', true);
    if (p) out.push([`Lo que más rápido se vende está en el tramo ${bucketName(p.k)}: tarda ${dys(p.v)} de mediana.`, { xdim: 'priceRange', metric: 'medDays', split: '' }]);
    const d = best('dow', 'sellRate', false);
    if (d) out.push([`Lo publicado en ${DOW_FULL[+d.k]} es lo que más se vende: el ${pct(d.v)}.`, { xdim: 'dow', metric: 'sellRate', split: '' }]);
    const h = best('hour', 'fast', false);
    if (h && h.v > 0) out.push([`De lo publicado entre las ${String(h.k).padStart(2, '0')}:00 y las ${String(h.k).padStart(2, '0')}:59, el ${pct(h.v)} se vende en menos de 3 días.`, { xdim: 'hour', metric: 'fast', split: '' }]);
    const sh = groupBy(items, 'shipping'), a1 = sh.get('1') || [], a0 = sh.get('0') || [];
    if (a1.length >= 8 && a0.length >= 8) {
      const r1 = METRICS.sellRate.f(a1), r0 = METRICS.sellRate.f(a0);
      out.push([`Con envío se vende el ${pct(r1)}, sin envío el ${pct(r0)}.`, { xdim: 'shipping', metric: 'sellRate', split: '' }]);
    }
    const sold = items.filter(isSold);
    if (sold.length >= 6) {
      const q1 = quant(sold.map(i => i.price), 0.25), q3 = quant(sold.map(i => i.price), 0.75);
      out.push([`La mitad de las ventas se cierra entre ${eur(q1)} y ${eur(q3)}: comprar por debajo de ${eur(q1)} deja margen.`, { xdim: 'priceRange', metric: 'sold', split: '' }]);
    }
    return out;
  }

  // ------------------------------------------------------------------ dibujo principal
  function draw() {
    if (!ROOT || !DATA) return;
    tipHide();
    const scroll = window.scrollY;
    ROOT.textContent = '';
    const items = filtered();

    // filtros: periodo, texto, búsquedas y lo seleccionado en los gráficos
    const bar = el('div', { cls: 'an-filters' });
    bar.appendChild(select([['7', '7 días'], ['30', '30 días'], ['90', '90 días'], ['180', '6 meses'], ['365', '1 año']], String(UI.days), v => { UI.days = +v; load(); }, 'Periodo'));
    const txt = el('input', { type: 'search', placeholder: 'Filtrar por palabras del título', value: (UI.text || []).join(' '), cls: 'an-txt', 'aria-label': 'Filtrar por título' });
    let tmo; txt.addEventListener('input', () => { clearTimeout(tmo); tmo = setTimeout(() => { UI.text = txt.value.toLowerCase().split(/\s+/).filter(Boolean); draw(); const t = ROOT.querySelector('.an-txt'); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); } }, 250); });
    bar.appendChild(txt);
    ROOT.appendChild(bar);

    const chips = el('div', { cls: 'filters an-chips' });
    DATA.searches.forEach(s => {
      const on = SEL.search && SEL.search.has(String(s.id));
      chips.appendChild(el('button', { cls: on ? 'on' : '', text: s.name + (s.kind === 'market' ? ' 📊' : ''), onclick: () => toggle('search', String(s.id)) }));
    });
    ROOT.appendChild(chips);

    const active = Object.keys(SEL).filter(d => SEL[d].size);
    if (active.length || (UI.text && UI.text.length)) {
      const af = el('div', { cls: 'an-active' }, [el('span', { cls: 'muted', text: 'Filtrando:' })]);
      active.forEach(d => SEL[d].forEach(k => af.appendChild(el('button', { cls: 'chip an-x', text: `${DIMS[d].label}: ${DIMS[d].name(k)} ✕`, onclick: () => toggle(d, k) }))));
      if (UI.text && UI.text.length) af.appendChild(el('button', { cls: 'chip an-x', text: `«${UI.text.join(' ')}» ✕`, onclick: () => { UI.text = []; draw(); } }));
      af.appendChild(el('button', { cls: 'btn sm ghost', text: 'Quitar todo', onclick: () => { for (const k in SEL) delete SEL[k]; UI.text = []; draw(); } }));
      ROOT.appendChild(af);
    }

    if (!ITEMS.length) {
      ROOT.appendChild(el('div', { cls: 'empty', text: 'Todavía no hay datos en este periodo. El bot necesita unas horas de rastreo; las ventas aparecen cuando revisa las fichas.' }));
      return;
    }

    ROOT.appendChild(kpis(items));

    // conclusiones automáticas
    const ins = insights(items);
    if (ins.length) {
      const list = el('div', { cls: 'an-ins' });
      ins.forEach(([t, cfg]) => list.appendChild(el('button', { cls: 'an-ins-i', onclick: () => { Object.assign(UI, cfg); draw(); const c = ROOT.querySelector('#an-cruce'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, [el('span', { text: '💡' }), el('span', { text: t })])));
      ROOT.appendChild(card('Conclusiones', 'Calculadas con los filtros actuales. Toca una para ver el gráfico que la respalda.', list));
    }

    // ---- cruce de datos
    const cruceBody = el('div');
    const ctr = el('div', { cls: 'an-ctr' });
    const dimOpts = Object.keys(DIMS).map(k => [k, DIMS[k].label]);
    ctr.appendChild(el('label', {}, ['Agrupar por', select(dimOpts, UI.xdim, v => { UI.xdim = v; if (UI.split === v) UI.split = ''; draw(); }, 'Agrupar por')]));
    ctr.appendChild(el('label', {}, ['Medir', select(Object.keys(METRICS).map(k => [k, METRICS[k].label]), UI.metric, v => { UI.metric = v; draw(); }, 'Métrica')]));
    ctr.appendChild(el('label', {}, ['Dividir por', select([['', 'Nada'], ...dimOpts.filter(d => d[0] !== UI.xdim)], UI.split, v => { UI.split = v; draw(); }, 'Dividir por')]));
    ctr.appendChild(el('label', {}, ['Orden', select([['natural', 'Natural'], ['desc', 'Mayor primero'], ['asc', 'Menor primero']], UI.sort, v => { UI.sort = v; draw(); }, 'Orden')]));
    cruceBody.appendChild(ctr);
    const pres = el('div', { cls: 'filters an-pres' });
    PRESETS.forEach(([l, cfg]) => pres.appendChild(el('button', { cls: UI.xdim === cfg.xdim && UI.metric === cfg.metric && UI.split === cfg.split ? 'on' : '', text: l, onclick: () => { Object.assign(UI, cfg); draw(); } })));
    cruceBody.appendChild(pres);
    const leg = el('div'); cruceBody.appendChild(leg);
    const cbox = el('div', { cls: 'an-plot' }); cruceBody.appendChild(cbox);
    const cruceCard = card('Cruza los datos', 'Toca una barra para filtrar todo el panel por ese valor.', cruceBody);
    cruceCard.id = 'an-cruce';
    ROOT.appendChild(cruceCard);

    // ---- evolución
    const tBody = el('div'), tLeg = el('div'), tBox = el('div', { cls: 'an-plot' });
    tBody.appendChild(tLeg); tBody.appendChild(tBox);
    ROOT.appendChild(card('Evolución', null, tBody, select([['counts', 'Nuevos y vendidos'], ['medSold', 'Precio de venta (mediana)'], ['medPrice', 'Precio de lo publicado (mediana)'], ['volume', '€ movidos en ventas'], ['medDays', 'Días hasta vender']], UI.time, v => { UI.time = v; draw(); }, 'Qué mostrar en el tiempo')));

    // ---- distribución de precios
    const hBody = el('div'), hBox = el('div', { cls: 'an-plot' });
    const hSeries = [{ name: 'Siguen en venta', color: SERIES(0) }, { name: 'Vendidos', color: SERIES(1) }];
    hBody.appendChild(legend(hSeries)); hBody.appendChild(hBox);
    ROOT.appendChild(card('Precios', 'Cuántos anuncios hay en cada tramo y cuántos se venden. Toca un tramo para filtrar.', hBody));

    // ---- mapa de calor
    const mBody = el('div'), mBox = el('div', { cls: 'an-plot' }), mLeg = el('div', { cls: 'an-qleg' });
    mBody.appendChild(mBox); mBody.appendChild(mLeg);
    ROOT.appendChild(card('Cuándo publicar', 'Por día y hora en que se publicó el anuncio. Toca una casilla para filtrar.', mBody,
      select([['sellRate', '% que se vende'], ['fast', '% vendido en < 3 días'], ['medDays', 'Días hasta vender'], ['count', 'Nº de anuncios'], ['medSold', 'Precio de venta']], UI.heat, v => { UI.heat = v; draw(); }, 'Métrica del mapa')));

    // ---- dispersión
    const sBody = el('div'), sLeg = el('div'), sBox = el('div', { cls: 'an-plot' }), sPick = el('div');
    sBody.appendChild(sLeg); sBody.appendChild(sBox); sBody.appendChild(sPick);
    ROOT.appendChild(card('Precio y rapidez de venta', 'Cada punto es una venta. Toca uno para ver el anuncio.', sBody));

    // ---- tabla
    const tabBody = el('div', { cls: 'an-table' });
    ROOT.appendChild(card('Anuncios', `${int(items.length)} con los filtros actuales`, tabBody));

    // ================= pintar (tras insertar, para medir el ancho)
    // cruce
    {
      const base = filtered(UI.xdim);
      const g = groupBy(base, UI.xdim);
      let keys = DIMS[UI.xdim].order ? DIMS[UI.xdim].order().filter(k => g.has(k)) : [...g.keys()];
      const val = k => METRICS[UI.metric].f(g.get(k) || []);
      if (UI.sort === 'natural') {
        if (!DIMS[UI.xdim].order) keys.sort((a, b) => g.get(b).length - g.get(a).length);
      } else {
        const dir = UI.sort === 'asc' ? 1 : -1;
        keys.sort((a, b) => { const va = val(a), vb = val(b); if (va == null) return 1; if (vb == null) return -1; return dir * (va - vb); });
      }
      const top = DIMS[UI.xdim].top || 20; if (keys.length > top) keys = keys.slice(0, top);
      let series = [{ name: METRICS[UI.metric].label, color: SERIES(0) }], splitKeys = null;
      if (UI.split) {
        const sg = groupBy(base, UI.split);
        let sk = DIMS[UI.split].order ? DIMS[UI.split].order().filter(k => sg.has(k)) : [...sg.keys()].sort((a, b) => sg.get(b).length - sg.get(a).length);
        const other = sk.length > 4 ? sk.slice(3) : [];
        splitKeys = sk.length > 4 ? sk.slice(0, 3).map(k => [k]).concat([other]) : sk.map(k => [k]);
        series = splitKeys.map((ks, i) => ({ name: ks.length > 1 ? 'Otros' : DIMS[UI.split].name(ks[0]), color: ks.length > 1 ? 'var(--mute)' : SERIES(i) }));
      }
      const rows = keys.map(k => {
        const a = g.get(k) || [];
        const vals = splitKeys ? splitKeys.map(ks => { const sub = a.filter(it => DIMS[UI.split].keys(it).some(x => ks.includes(x))); return { v: sub.length ? METRICS[UI.metric].f(sub) : null, n: sampleOf(UI.metric, sub) }; })
          : [{ v: METRICS[UI.metric].f(a), n: sampleOf(UI.metric, a) }];
        return { key: k, label: DIMS[UI.xdim].name(k), vals };
      });
      if (series.length > 1) leg.appendChild(legend(series));
      if (!rows.length) cbox.appendChild(el('p', { cls: 'muted', text: 'Sin datos con estos filtros.' }));
      else hbars(cbox, rows, { series, fmt: METRICS[UI.metric].fmt, selected: SEL[UI.xdim], onClick: k => toggle(UI.xdim, k), aria: `${METRICS[UI.metric].label} por ${DIMS[UI.xdim].label}` });
      cbox.appendChild(el('p', { cls: 'muted an-note', text: 'Precios y días son medianas. Las barras claras con «·» tienen menos de ' + MIN_N + ' anuncios: tómalas con cautela.' }));
    }

    // evolución
    {
      const days = UI.days, now = DATA.now, weekly = days > 60;
      const keyOf = ts => { if (!weekly) return dayKey(ts); const d = new Date(ts * 1000); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return dayKey(d.getTime() / 1000); };
      const keys = []; const seen = new Set();
      for (let t = now - days * DAY; t <= now + 1; t += DAY) { const k = keyOf(t); if (!seen.has(k)) { seen.add(k); keys.push(k); } }
      const pubBy = new Map(), soldBy = new Map();
      items.forEach(it => {
        if (it.pub) { const k = keyOf(it.pub); if (seen.has(k)) { if (!pubBy.has(k)) pubBy.set(k, []); pubBy.get(k).push(it); } }
        if (it.sold && it.changed) { const k = keyOf(it.changed); if (seen.has(k)) { if (!soldBy.has(k)) soldBy.set(k, []); soldBy.get(k).push(it); } }
      });
      const lab = k => (weekly ? 'sem. ' : '') + shortDay(k);
      let cols, series, fmt;
      if (UI.time === 'counts') {
        series = [{ name: 'Nuevos', color: SERIES(0) }, { name: 'Vendidos', color: SERIES(1) }];
        cols = keys.map(k => ({ key: k, label: shortDay(k), tipHead: lab(k), vals: [(pubBy.get(k) || []).length, (soldBy.get(k) || []).length] }));
        fmt = int;
        tLeg.appendChild(legend(series));
      } else {
        const m = UI.time, src = m === 'medPrice' ? pubBy : soldBy;
        series = [{ name: METRICS[m].label, color: SERIES(m === 'medPrice' ? 0 : 1) }];
        fmt = METRICS[m].fmt;
        cols = keys.map(k => { const a = src.get(k) || []; const v = a.length ? METRICS[m].f(a) : null; return { key: k, label: shortDay(k), tipHead: lab(k), vals: [v], low: a.length < 3, tip: [{ color: series[0].color, value: v == null ? 'sin datos' : fmt(v), label: `${a.length} ${m === 'medPrice' ? 'publicados' : 'vendidos'}` }] }; });
      }
      vbars(tBox, cols, { series, fmt, aria: 'Evolución en el tiempo' });
    }

    // precios
    if (BUCKETS) {
      const base = filtered('priceRange');
      const g = groupBy(base, 'priceRange');
      const cols = bucketOrder().filter(k => g.has(k) || /^\d+$/.test(k)).map(k => {
        const a = g.get(k) || [], s = a.filter(isSold).length;
        return { key: k, label: k === 'lt' ? '<' + eur(BUCKETS.lo) : k === 'gt' ? '≥' + eur(BUCKETS.hi) : eur(BUCKETS.lo + (+k) * BUCKETS.step), tipHead: bucketName(k), vals: [a.length - s, s], tip: [{ color: SERIES(0), value: int(a.length - s), label: 'siguen en venta' }, { color: SERIES(1), value: int(s), label: 'vendidos' }, { value: a.length ? pct(s / a.length * 100) : '–', label: 'se vende' }] };
      });
      vbars(hBox, cols, { series: hSeries, fmt: int, selected: SEL.priceRange, onClick: k => toggle('priceRange', k), aria: 'Distribución de precios' });
    } else hBox.appendChild(el('p', { cls: 'muted', text: 'Faltan anuncios con precio.' }));

    // mapa de calor
    {
      const base = filtered(['dow', 'hour']);
      const r = heatmap(mBox, base, UI.heat);
      const f = METRICS[UI.heat].fmt;
      mLeg.appendChild(el('span', { text: f(r.lo) }));
      for (let i = 1; i <= 5; i++) mLeg.appendChild(el('i', { style: `background:var(--q${i})` }));
      mLeg.appendChild(el('span', { text: f(r.hi) }));
      mLeg.appendChild(el('span', { cls: 'muted', text: ' · gris: pocos datos' }));
    }

    // dispersión
    {
      const counts = new Map(); items.filter(isSold).forEach(i => i.searches.forEach(s => counts.set(s, (counts.get(s) || 0) + 1)));
      const topS = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(e => e[0]);
      const colorOf = p => { const i = topS.findIndex(s => p.searches.includes(s)); return i >= 0 ? SERIES(i) : 'var(--mute)'; };
      const ser = topS.map((s, i) => ({ name: SNAMES[String(s)] || '?', color: SERIES(i) }));
      if (counts.size > 3) ser.push({ name: 'Otras', color: 'var(--mute)' });
      if (ser.length > 1) sLeg.appendChild(legend(ser, 'dot'));
      const onPick = p => { pickedPoint = p.id; showPick(sPick, p); scatter(sBox, items, colorOf, onPick); };
      scatter(sBox, items, colorOf, onPick);
      const picked = pickedPoint && items.find(i => i.id === pickedPoint);
      if (picked) showPick(sPick, picked);
    }

    // tabla
    table(tabBody, items);

    window.scrollTo(0, scroll);
  }

  function showPick(box, p) {
    box.textContent = '';
    const a = el('a', { href: 'https://es.wallapop.com/item/' + p.slug, cls: 'an-pick' }, [
      p.image ? el('img', { src: p.image, alt: '', loading: 'lazy' }) : null,
      el('div', {}, [el('b', { text: eur(p.price) + (p.first && p.first > p.price ? ' (pedía ' + eur(p.first) + ')' : '') }), el('div', { cls: 'muted', text: p.title }), el('div', { cls: 'muted', text: `${STATUS[p.status]} en ${dys(p.days)}${p.city ? ' · ' + p.city : ''}` })]),
    ]);
    box.appendChild(a);
  }

  function table(box, items) {
    box.textContent = '';
    const cols = [
      ['title', 'Anuncio', i => i.title, false],
      ['price', 'Precio', i => i.price, true],
      ['status', 'Estado', i => STATUS[i.status], false],
      ['days', 'Días', i => i.days, true],
      ['drops', 'Bajadas', i => i.drops, true],
      ['pub', 'Publicado', i => i.pub, true],
    ];
    const s = UI.tableSort, c = cols.find(x => x[0] === s.k) || cols[5];
    const sorted = items.slice().sort((a, b) => { const va = c[2](a), vb = c[2](b); if (va == null) return 1; if (vb == null) return -1; return (va > vb ? 1 : va < vb ? -1 : 0) * s.d; });
    const t = el('table');
    const hr = el('tr');
    cols.forEach(([k, l, , num]) => hr.appendChild(el('th', { cls: (num ? 'n ' : '') + 'an-th', text: l + (s.k === k ? (s.d > 0 ? ' ▲' : ' ▼') : ''), onclick: () => { UI.tableSort = { k, d: s.k === k ? -s.d : (num ? -1 : 1) }; table(box, items); } })));
    t.appendChild(hr);
    sorted.slice(0, UI.tableN).forEach(i => {
      const tr = el('tr');
      tr.appendChild(el('td', {}, [el('a', { href: 'https://es.wallapop.com/item/' + i.slug, text: i.title.length > 42 ? i.title.slice(0, 41) + '…' : i.title })]));
      tr.appendChild(el('td', { cls: 'n', text: eur(i.price) }));
      tr.appendChild(el('td', { text: STATUS[i.status] || i.status }));
      tr.appendChild(el('td', { cls: 'n', text: i.days == null ? '–' : dys(i.days) }));
      tr.appendChild(el('td', { cls: 'n', text: String(i.drops) }));
      tr.appendChild(el('td', { cls: 'n', text: i.pub ? shortDay(dayKey(i.pub)) : '–' }));
      t.appendChild(tr);
    });
    box.appendChild(el('div', { cls: 'an-tscroll' }, [t]));
    if (sorted.length > UI.tableN) box.appendChild(el('button', { cls: 'btn sm ghost', text: `Ver ${Math.min(100, sorted.length - UI.tableN)} más`, onclick: () => { UI.tableN += 100; table(box, items); } }));
  }

  async function load() {
    if (ROOT) ROOT.classList.add('an-loading');
    try {
      const d = await API('/api/analytics?days=' + UI.days);
      prepare(d);
      // limpia selecciones que ya no existen
      if (SEL.search) [...SEL.search].forEach(k => { if (!SNAMES[k]) SEL.search.delete(k); });
      draw();
    } catch (e) {
      if (ROOT && e.message !== 'token') { ROOT.textContent = ''; ROOT.appendChild(el('div', { cls: 'empty', text: 'No llego al bot: ' + e.message })); }
    } finally { if (ROOT) ROOT.classList.remove('an-loading'); }
  }

  let resizeT;
  window.addEventListener('resize', () => { clearTimeout(resizeT); resizeT = setTimeout(() => { if (ROOT && document.body.contains(ROOT)) draw(); }, 200); });

  window.renderAnalytics = function (view, api) {
    API = api;
    view.textContent = '';
    ROOT = el('div', { cls: 'an-root' });
    view.appendChild(ROOT);
    if (!TIP) { TIP = el('div', { cls: 'an-tip', role: 'status' }); document.body.appendChild(TIP); document.addEventListener('scroll', tipHide, { passive: true }); }
    if (DATA && DATA.days === UI.days) draw();
    load();
  };
})();
