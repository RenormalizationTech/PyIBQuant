/* PyIBQuant's native Canvas renderer. Coordinates use CSS pixels; backing pixels
 * scale with devicePixelRatio. The viewport is expressed in bar indices, so
 * closed-market gaps occupy no space and both panes always share one time axis. */
class MarketChart {
  constructor(canvas, legend, interval) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.legend = legend;
    this.interval = interval;
    this.bars = [];
    this.left = 0;
    this.count = 0;
    this.hover = null;
    this.pointers = new Map();
    this.frame = null;
    this.colors = {background: '#0b1018', grid: '#1b2838', text: '#93a9c2', up: '#38c9a0', down: '#ef7481'};
    this.number = new Intl.NumberFormat('en-US', {maximumFractionDigits: 2});
    this.compact = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
    this.dateFormat = new Intl.DateTimeFormat('en-US', {timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric'});
    this.setInterval(interval);
    this.bindEvents();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(canvas.parentElement);
    this.resize();
  }

  setInterval(interval) {
    this.interval = interval;
    this.timeFormat = new Intl.DateTimeFormat('en-GB', {timeZone: 'UTC', hour: '2-digit', minute: '2-digit', ...(interval === '30s' ? {second: '2-digit'} : {})});
  }

  resize() {
    const box = this.canvas.parentElement.getBoundingClientRect();
    this.width = Math.max(1, box.width);
    this.height = Math.max(1, box.height);
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.requestDraw();
  }

  setData(bars) {
    const following = !this.bars.length || this.left + this.count >= this.bars.length - 0.05;
    const fitted = !this.bars.length || this.count >= this.bars.length;
    this.bars = bars;
    if (fitted) this.count = bars.length;
    this.count = Math.min(this.count || bars.length, bars.length);
    if (following) this.left = bars.length - this.count;
    this.clampView();
    this.requestDraw();
  }

  clampView() {
    this.left = Math.max(0, Math.min(this.left, Math.max(0, this.bars.length - this.count)));
  }

  fit() {
    this.left = 0;
    this.count = this.bars.length;
    this.requestDraw();
  }

  latest() {
    this.left = Math.max(0, this.bars.length - this.count);
    this.requestDraw();
  }

  zoom(factor, pixel) {
    if (!this.bars.length || !this.plot) return;
    const fraction = Math.max(0, Math.min(1, (pixel - this.plot.x) / this.plot.w));
    const anchor = this.left + fraction * this.count;
    this.count = Math.max(Math.min(8, this.bars.length), Math.min(this.bars.length, this.count * factor));
    this.left = anchor - fraction * this.count;
    this.clampView();
    this.requestDraw();
  }

  pan(pixels) {
    if (!this.plot) return;
    this.left -= pixels / this.plot.w * this.count;
    this.clampView();
    this.requestDraw();
  }

  position(event) {
    const rect = this.canvas.getBoundingClientRect();
    return {x: event.clientX - rect.left, y: event.clientY - rect.top};
  }

  bindEvents() {
    const canvas = this.canvas;
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      const position = this.position(event);
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.height : 1);
      this.zoom(Math.exp(Math.max(-1, Math.min(1, delta * 0.002))), position.x);
    }, {passive: false});
    canvas.addEventListener('pointerdown', event => {
      canvas.focus({preventScroll: true});
      canvas.setPointerCapture(event.pointerId);
      this.pointers.set(event.pointerId, this.position(event));
      this.hover = null;
      canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('pointermove', event => {
      const position = this.position(event);
      if (this.pointers.has(event.pointerId)) {
        const before = [...this.pointers.values()];
        const previous = this.pointers.get(event.pointerId);
        this.pointers.set(event.pointerId, position);
        const after = [...this.pointers.values()];
        if (before.length === 2) {
          const oldDistance = Math.hypot(before[1].x - before[0].x, before[1].y - before[0].y);
          const distance = Math.hypot(after[1].x - after[0].x, after[1].y - after[0].y);
          if (distance > 4 && oldDistance > 4) this.zoom(oldDistance / distance, (before[0].x + before[1].x) / 2);
          this.pan((after[0].x + after[1].x - before[0].x - before[1].x) / 2);
        } else if (before.length === 1) this.pan(position.x - previous.x);
      } else this.hover = position;
      this.requestDraw();
    });
    const release = event => {
      this.pointers.delete(event.pointerId);
      canvas.style.cursor = 'crosshair';
      this.hover = null;
      this.requestDraw();
    };
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', release);
    canvas.addEventListener('lostpointercapture', release);
    canvas.addEventListener('pointerleave', () => {
      this.hover = null;
      this.requestDraw();
    });
    canvas.addEventListener('dblclick', () => this.fit());
    canvas.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', '+', '=', '-', 'Home', 'End', 'Escape'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Home') this.fit();
      else if (event.key === 'End') this.latest();
      else if (event.key === 'Escape') { this.hover = null; this.requestDraw(); }
      else if (event.key === 'ArrowLeft') this.pan(this.plot.w * 0.15);
      else if (event.key === 'ArrowRight') this.pan(-this.plot.w * 0.15);
      else this.zoom(event.key === '-' ? 1.25 : 0.8, this.width / 2);
    });
  }

  requestDraw() {
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => { this.frame = null; this.draw(); });
  }

  date(time) { return new Date(typeof time === 'number' ? time * 1000 : `${time}T00:00:00Z`); }
  timeLabel(time, full = false) {
    const date = this.date(time);
    if (typeof time !== 'number') return this.dateFormat.format(date);
    return full ? `${this.dateFormat.format(date)} ${this.timeFormat.format(date)} UTC` : this.timeFormat.format(date);
  }

  line(x1, y1, x2, y2, color, dash = []) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash(dash);
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  label(text, x, y, background, foreground = '#e1e8f0', align = 'left') {
    const ctx = this.ctx;
    const width = ctx.measureText(text).width + 12;
    x = Math.max(0, Math.min(x - (align === 'center' ? width / 2 : 0), this.width - width));
    y = Math.max(0, Math.min(y, this.height - 22));
    ctx.fillStyle = background;
    ctx.fillRect(x, y, width, 22);
    ctx.fillStyle = foreground;
    ctx.fillText(text, x + 6, y + 15);
  }

  draw() {
    const ctx = this.ctx;
    const {width, height, colors} = this;
    ctx.fillStyle = colors.background;
    ctx.fillRect(0, 0, width, height);
    ctx.font = '11px ui-monospace, monospace';
    if (!this.bars.length) {
      ctx.fillStyle = colors.text;
      ctx.fillText('No bars to display', 24, 36);
      this.legend.textContent = '';
      return;
    }
    const first = Math.max(0, Math.floor(this.left));
    const last = Math.min(this.bars.length, Math.ceil(this.left + this.count));
    const visible = this.bars.slice(first, last);
    let low = Infinity, high = -Infinity, volumeMax = 1;
    for (const bar of visible) {
      low = Math.min(low, bar.low); high = Math.max(high, bar.high);
      volumeMax = Math.max(volumeMax, bar.volume);
    }
    const padding = Math.max((high - low) * 0.08, Math.abs(high) * 0.0001, 0.01);
    low -= padding; high += padding;
    const axis = Math.max(64, ctx.measureText(this.number.format(high)).width + 20);
    const plot = this.plot = {x: 12, y: 16, w: Math.max(1, width - axis - 12), h: Math.max(1, height - 52)};
    const priceBottom = plot.y + plot.h * 0.76;
    const volumeTop = priceBottom + 22;
    const bottom = plot.y + plot.h;
    const volumeHeight = Math.max(1, bottom - volumeTop);
    const step = plot.w / this.count;
    const x = index => plot.x + (index - this.left + 0.5) * step;
    const y = price => plot.y + (high - price) / (high - low) * (priceBottom - plot.y);
    ctx.fillStyle = colors.text;
    // Nice decimal steps keep the price axis readable as the view changes.
    const rough = (high - low) / Math.max(2, Math.floor((priceBottom - plot.y) / 60));
    const power = 10 ** Math.floor(Math.log10(rough));
    const tick = [1, 2, 5, 10].find(value => value * power >= rough) * power;
    const decimals = Math.max(2, Math.min(8, -Math.floor(Math.log10(tick))));
    for (let price = Math.ceil(low / tick) * tick; price <= high; price += tick) {
      const py = y(price);
      this.line(plot.x, py, plot.x + plot.w, py, colors.grid);
      ctx.fillText(price.toFixed(decimals), plot.x + plot.w + 8, py + 4);
    }
    const timeTicks = Math.max(1, Math.floor(plot.w / (this.interval === '1d' ? 135 : 110)));
    const stride = Math.max(1, Math.ceil(this.count / timeTicks));
    for (let index = Math.ceil(this.left / stride) * stride; index < last; index += stride) {
      const px = x(index);
      this.line(px, plot.y, px, bottom, colors.grid);
      const text = this.timeLabel(this.bars[index].time);
      const labelWidth = ctx.measureText(text).width;
      ctx.fillText(text, Math.max(plot.x, Math.min(px - labelWidth / 2, plot.x + plot.w - labelWidth)), bottom + 23);
    }
    this.line(plot.x + plot.w, plot.y, plot.x + plot.w, bottom, '#314258');
    this.line(plot.x, priceBottom + 11, plot.x + plot.w, priceBottom + 11, '#314258');
    this.line(plot.x, bottom, plot.x + plot.w, bottom, '#314258');
    ctx.fillText(this.compact.format(volumeMax), plot.x + plot.w + 8, volumeTop + 8);
    ctx.fillText('0', plot.x + plot.w + 8, bottom);
    ctx.fillText('VOLUME', plot.x + 6, volumeTop + 8);
    ctx.save();
    ctx.beginPath(); ctx.rect(plot.x, plot.y, plot.w, plot.h); ctx.clip();
    const candleWidth = Math.max(1, step * 0.7);
    for (let index = first; index < last; index++) {
      const bar = this.bars[index];
      const px = x(index);
      const color = bar.close >= bar.open ? colors.up : colors.down;
      this.line(px, y(bar.high), px, y(bar.low), color);
      ctx.fillStyle = color;
      ctx.fillRect(px - candleWidth / 2, Math.min(y(bar.open), y(bar.close)), candleWidth, Math.max(1, Math.abs(y(bar.open) - y(bar.close))));
      const vh = bar.volume / volumeMax * volumeHeight;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(px - candleWidth / 2, bottom - vh, candleWidth, vh);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    const latest = this.bars.at(-1);
    const latestY = y(latest.close);
    if (latestY >= plot.y && latestY <= priceBottom) {
      const color = latest.close >= latest.open ? colors.up : colors.down;
      this.line(plot.x, latestY, plot.x + plot.w, latestY, color, [3, 4]);
      this.label(this.number.format(latest.close), plot.x + plot.w, latestY - 11, color, '#0b1018');
    }
    let selected = latest;
    const hover = this.hover;
    if (hover && hover.x >= plot.x && hover.x <= plot.x + plot.w && hover.y >= plot.y && hover.y <= bottom) {
      const index = Math.max(first, Math.min(last - 1, Math.floor(this.left + (hover.x - plot.x) / step)));
      selected = this.bars[index];
      const px = x(index);
      this.line(px, plot.y, px, bottom, '#a5b9d0', [4, 4]);
      this.line(plot.x, hover.y, plot.x + plot.w, hover.y, '#a5b9d0', [4, 4]);
      const value = hover.y <= priceBottom ? this.number.format(high - (hover.y - plot.y) / (priceBottom - plot.y) * (high - low)) : this.compact.format(Math.max(0, (bottom - hover.y) / volumeHeight * volumeMax));
      this.label(value, plot.x + plot.w, hover.y - 11, '#33465d');
      this.label(this.timeLabel(selected.time, true), px, bottom + 5, '#33465d', '#e1e8f0', 'center');
    }
    this.legend.textContent = `${this.timeLabel(selected.time, true)}   O ${this.number.format(selected.open)}   H ${this.number.format(selected.high)}   L ${this.number.format(selected.low)}   C ${this.number.format(selected.close)}   Vol ${this.number.format(selected.volume)}`;
  }
}

const initial = JSON.parse(document.getElementById('chart-data').textContent);
const liveEndpoint = __LIVE_ENDPOINT__;
const controlsEnabled = __CONTROLS_ENABLED__;
const status = document.getElementById('status');
const error = document.getElementById('error');
const fields = document.getElementById('selection-fields');
const symbolInput = document.getElementById('symbol-input');
const intervalInput = document.getElementById('interval-input');
const durationInput = document.getElementById('duration-input');
let currentSymbol = initial.symbol;
let currentInterval = initial.interval;
let loading = false;
let selectionError = '';
let generation = 0;
symbolInput.value = initial.symbol;
intervalInput.value = initial.interval;
durationInput.value = initial.duration || '1 D';
fields.disabled = !controlsEnabled;
if (controlsEnabled) document.getElementById('controls-note').textContent = 'US stocks and ETFs · History examples: 1 D, 2 W, 6 M · Load chart or press Enter';
const chart = new MarketChart(document.getElementById('market-canvas'), document.getElementById('legend'), initial.interval);
function showError(message) { error.hidden = !message; error.textContent = message || ''; }
function draw(payload, reset = false) {
  reset = reset || payload.symbol !== currentSymbol || payload.interval !== currentInterval;
  currentSymbol = payload.symbol;
  currentInterval = payload.interval;
  document.getElementById('symbol').textContent = payload.symbol;
  document.getElementById('meta').textContent = `${payload.interval} · ${payload.provider} · USD`;
  document.title = `${payload.symbol} · PyIBQuant`;
  chart.setInterval(payload.interval);
  if (reset) { chart.bars = []; chart.hover = null; }
  chart.setData(payload.bars);
  status.textContent = `${payload.status} · ${payload.bars.length.toLocaleString()} bars${payload.live && liveEndpoint ? ' · Updates checked every 2s' : ''}`;
  showError([selectionError, payload.error, ...(payload.warnings || [])].filter(Boolean).join('\n'));
}
draw(initial);
document.getElementById('fit').onclick = () => chart.fit();
document.getElementById('latest').onclick = () => chart.latest();
document.getElementById('chart-controls').addEventListener('submit', async event => {
  event.preventDefault();
  if (!controlsEnabled || loading) return;
  const selection = {symbol: symbolInput.value.trim().toUpperCase(), interval: intervalInput.value, duration: durationInput.value.trim()};
  loading = true;
  generation++;
  fields.disabled = true;
  status.textContent = `Loading ${selection.symbol} · ${selection.interval}…`;
  document.getElementById('chart').setAttribute('aria-busy', 'true');
  selectionError = '';
  showError('');
  try {
    const response = await fetch('/chart', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(selection)});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Chart server returned ${response.status}`);
    symbolInput.value = payload.symbol;
    durationInput.value = payload.duration;
    draw(payload, true);
  } catch (e) {
    status.textContent = `Could not load ${selection.symbol}. Showing ${currentSymbol} · ${currentInterval}.`;
    selectionError = e.message;
    showError(selectionError);
  } finally {
    loading = false;
    fields.disabled = false;
    document.getElementById('chart').setAttribute('aria-busy', 'false');
  }
});
async function poll() {
  const started = generation;
  try {
    if (loading) return;
    const response = await fetch('/data', {cache: 'no-store'});
    if (!response.ok) throw new Error(`Chart server returned ${response.status}`);
    const payload = await response.json();
    if (!loading && started === generation) draw(payload);
  } catch (e) {
    if (!loading && started === generation) {
      status.textContent = 'Chart connection interrupted';
      showError(`${e.message}. Keep the Python process running; retrying…`);
    }
  } finally { setTimeout(poll, 2000); }
}
if (liveEndpoint) setTimeout(poll, 2000);
