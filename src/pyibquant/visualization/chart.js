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
    this.sessions = [];
    this.sessionDates = new Map();
    this.dayCache = new Map();
    this.showSessions = true;
    this.left = 0;
    this.count = 0;
    this.rightMargin = 0.1;
    this.tickOffset = 0;
    this.hover = null;
    this.manualRange = null;
    this.priceRange = null;
    this.dragMode = null;
    this.pointers = new Map();
    this.frame = null;
    this.colors = {background: '#0b1018', grid: '#1b2838', text: '#93a9c2', up: '#38c9a0', down: '#ef7481'};
    this.number = new Intl.NumberFormat('en-US', {maximumFractionDigits: 2});
    this.compact = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
    this.dateFormat = new Intl.DateTimeFormat('en-US', {timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric'});
    this.intradayDateFormat = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric'});
    this.zoneFormat = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', timeZoneName: 'short'});
    this.dayFormat = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'});
    this.clockFormat = new Intl.DateTimeFormat('en-GB', {timeZone: 'America/New_York', hourCycle: 'h23', hour: '2-digit', minute: '2-digit', second: '2-digit'});
    this.setInterval(interval);
    this.bindEvents();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(canvas.parentElement);
    this.resize();
  }

  setInterval(interval) {
    this.interval = interval;
    this.timeFormat = new Intl.DateTimeFormat('en-GB', {timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', ...(interval === '30s' ? {second: '2-digit'} : {})});
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

  day(time) {
    if (typeof time !== 'number') return time;
    if (!this.dayCache.has(time)) this.dayCache.set(time, this.dayFormat.format(this.date(time)));
    return this.dayCache.get(time);
  }

  setSessions(sessions) {
    this.sessions = sessions || [];
    this.sessionDates = new Map();
    for (const session of this.sessions) {
      if (!this.sessionDates.has(session.date)) this.sessionDates.set(session.date, []);
      this.sessionDates.get(session.date).push(session);
    }
  }

  intervalSeconds() {
    return {'30s': 30, '1min': 60, '5min': 300, '15min': 900, '30min': 1800,
      '1h': 3600, '2h': 7200, '4h': 14400}[this.interval];
  }

  barBoundary(time) {
    const parts = Object.fromEntries(this.clockFormat.formatToParts(this.date(time)).map(p => [p.type, p.value]));
    const local = Number(parts.hour) * 3600 + Number(parts.minute) * 60 + Number(parts.second);
    const seconds = this.intervalSeconds();
    // IBKR aligns multi-hour candles to the local clock, shortening the 09:30 opener.
    return time + seconds - local % seconds;
  }

  sessionBands(first, last, x, step, plot) {
    if (!this.showSessions || !this.intervalSeconds()) return;
    const ctx = this.ctx;
    ctx.save();
    ctx.beginPath(); ctx.rect(plot.x, plot.y, plot.w, plot.h); ctx.clip();
    for (let index = first; index < last; index++) {
      const time = this.bars[index].time;
      const day = this.day(time);
      const sessions = this.sessionDates.get(day) || [];
      const extended = sessions.filter(session => !session.regular);
      const regular = sessions.filter(session => session.regular);
      if (extended.some(session => time >= session.start && time < session.end)) {
        const end = Math.min(this.barBoundary(time), ...extended.filter(s => s.end > time).map(s => s.end));
        // Interpolate actual session boundaries inside large candles as well.
        const edges = [time, end, ...regular.flatMap(s => [s.start, s.end]).filter(t => t > time && t < end)].sort((a, b) => a - b);
        for (let part = 1; part < edges.length; part++) {
          if (regular.some(s => edges[part - 1] >= s.start && edges[part - 1] < s.end)) continue;
          ctx.fillStyle = '#182239';
          ctx.fillRect(x(index) - step / 2 + (edges[part - 1] - time) / (end - time) * step,
            plot.y, (edges[part] - edges[part - 1]) / (end - time) * step, plot.h);
        }
      }
      if (index > 0 && day !== this.day(this.bars[index - 1].time)) {
        this.line(x(index) - step / 2, plot.y, x(index) - step / 2, plot.y + plot.h, '#42516a', [3, 4]);
      }
    }
    ctx.restore();
  }

  setData(bars) {
    const following = !this.bars.length || this.isFollowing();
    const fitted = !this.bars.length || this.isFitted();
    const prepended = this.bars.length ? bars.findIndex(bar => bar.time === this.bars[0].time) : 0;
    if (!this.bars.length) this.tickOffset = 0;
    else if (prepended > 0) this.tickOffset += prepended;
    this.bars = bars;
    if (prepended > 0) this.left += prepended;
    else if (fitted) this.count = this.fullCount();
    this.count = Math.min(this.count || this.fullCount(), this.fullCount());
    if (following && prepended <= 0) this.left = this.latestLeft();
    this.clampView();
    this.requestDraw();
  }

  fullCount() { return this.bars.length / (1 - this.rightMargin); }
  latestLeft() { return Math.max(0, this.bars.length - this.count * (1 - this.rightMargin)); }
  isFollowing() { return this.left >= this.latestLeft() - 0.05; }
  isFitted() { return this.left < 0.05 && this.count >= this.fullCount() - 0.05; }

  clampView() {
    this.left = Math.max(0, Math.min(this.left, this.latestLeft()));
  }

  fitTime() {
    this.left = 0;
    this.count = this.fullCount();
    this.requestDraw();
  }

  fit() {
    this.fitTime();
    this.setAutoscale(true);
  }

  setRightMargin(fraction) {
    if (!Number.isFinite(fraction) || fraction < 0 || fraction > 0.4) return;
    const following = this.isFollowing();
    const fitted = this.isFitted();
    this.rightMargin = fraction;
    if (fitted) this.count = this.fullCount();
    this.count = Math.min(this.count, this.fullCount());
    if (following) this.left = this.latestLeft();
    this.clampView();
    this.requestDraw();
  }

  setAutoscale(enabled) {
    if (!enabled && (!this.bars.length || !this.priceRange)) return;
    this.manualRange = enabled ? null : {...this.priceRange};
    this.onScaleChange?.();
    this.requestDraw();
  }

  setPriceRange(low, high) {
    const span = high - low;
    // Stop extreme gestures before floating-point precision collapses the scale.
    if (![low, high, span].every(Number.isFinite) || span <= Math.max(1e-8, Math.abs(low) * 1e-12, Math.abs(high) * 1e-12)) return;
    this.manualRange = {low, high};
    this.onScaleChange?.();
    this.requestDraw();
  }

  scalePrice(pixels) {
    if (!this.bars.length || !this.priceRange) return;
    const {low, high} = this.manualRange || this.priceRange;
    const center = low + (high - low) / 2;
    const half = (high - low) / 2 * Math.exp(Math.max(-1, Math.min(1, pixels * 0.01)));
    this.setPriceRange(center - half, center + half);
  }

  panPrice(pixels) {
    if (!this.manualRange || !this.bars.length || !this.priceHeight) return;
    const {low, high} = this.manualRange;
    const shift = pixels / this.priceHeight * (high - low);
    this.setPriceRange(low + shift, high + shift);
  }

  region(position) {
    const plot = this.plot;
    if (!this.bars.length || !plot || position.y < plot.y) return null;
    if (position.y <= plot.y + this.priceHeight) {
      if (position.x >= plot.x + plot.w) return 'price-axis';
      if (position.x >= plot.x) return 'price';
    }
    if (position.x >= plot.x && position.x < plot.x + plot.w && position.y <= plot.y + plot.h) return 'volume';
    if (position.x >= plot.x && position.x < plot.x + plot.w && position.y <= plot.y + plot.h + 36) return 'time-axis';
    return null;
  }

  cursor(position) {
    const region = this.region(position);
    return region === 'price-axis' ? 'ns-resize' : region === 'time-axis' ? 'ew-resize' : 'crosshair';
  }

  latest() {
    this.left = this.latestLeft();
    this.requestDraw();
  }

  zoom(factor, pixel) {
    if (!this.bars.length || !this.plot) return;
    const fraction = Math.max(0, Math.min(1, (pixel - this.plot.x) / this.plot.w));
    const anchor = this.left + fraction * this.count;
    this.count = Math.max(Math.min(8, this.bars.length) / (1 - this.rightMargin), Math.min(this.fullCount(), this.count * factor));
    this.left = anchor - fraction * this.count;
    this.clampView();
    this.requestDraw();
    if (factor > 1 && this.left <= Math.max(2, this.count * 0.15)) this.onOlder?.();
  }

  pan(pixels) {
    if (!this.plot) return;
    this.left -= pixels / this.plot.w * this.count;
    this.clampView();
    this.requestDraw();
    if (pixels > 0 && this.left <= Math.max(2, this.count * 0.15)) this.onOlder?.();
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
      if (event.button !== 0) return;
      const position = this.position(event);
      const region = this.region(position);
      if (!region) return;
      canvas.focus({preventScroll: true});
      canvas.setPointerCapture(event.pointerId);
      if (!this.pointers.size) this.dragMode = region;
      this.pointers.set(event.pointerId, position);
      this.hover = null;
      canvas.style.cursor = this.dragMode.endsWith('axis') ? this.cursor(position) : 'grabbing';
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
        } else if (before.length === 1) {
          if (this.dragMode === 'price-axis') this.scalePrice(position.y - previous.y);
          else if (this.dragMode === 'time-axis') {
            const edge = this.isFollowing() ? 1 - this.rightMargin : 1;
            this.zoom(Math.exp(Math.max(-1, Math.min(1, (previous.x - position.x) * 0.01))), this.plot.x + this.plot.w * edge);
          }
          else {
            this.pan(position.x - previous.x);
            if (this.dragMode === 'price') this.panPrice(position.y - previous.y);
          }
        }
      } else {
        this.hover = position;
        canvas.style.cursor = this.cursor(position);
      }
      this.requestDraw();
    });
    const release = event => {
      this.pointers.delete(event.pointerId);
      if (!this.pointers.size) this.dragMode = null;
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
    canvas.addEventListener('dblclick', event => {
      const region = this.region(this.position(event));
      if (region === 'price-axis') this.setAutoscale(true);
      else if (region === 'time-axis') this.fitTime();
      else this.fit();
    });
    canvas.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'a', 'A', '+', '=', '-', 'Home', 'End', 'Escape'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Home') this.fit();
      else if (event.key === 'End') this.latest();
      else if (event.key.toLowerCase() === 'a') this.setAutoscale(this.manualRange !== null);
      else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        if (!this.manualRange) this.setAutoscale(false);
        this.panPrice(this.priceHeight * (event.key === 'ArrowUp' ? -0.15 : 0.15));
      }
      else if (event.key === 'Escape') { this.hover = null; this.requestDraw(); }
      else if (event.key === 'ArrowLeft') this.pan((this.plot?.w || 0) * 0.15);
      else if (event.key === 'ArrowRight') this.pan(-(this.plot?.w || 0) * 0.15);
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
    if (this.interval === '1y') return `${date.getUTCFullYear()}${full ? ' (calendar year)' : ''}`;
    if (typeof time !== 'number') return this.dateFormat.format(date);
    const zone = this.zoneFormat.formatToParts(date).find(part => part.type === 'timeZoneName').value;
    return full ? `${this.intradayDateFormat.format(date)} ${this.timeFormat.format(date)} ${zone}` : this.timeFormat.format(date);
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
      this.plot = null;
      this.priceRange = null;
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
    if (this.manualRange) ({low, high} = this.manualRange);
    this.priceRange = {low, high};
    const axis = Math.max(64, ctx.measureText(this.number.format(high)).width + 20);
    const plot = this.plot = {x: 12, y: 16, w: Math.max(1, width - axis - 12), h: Math.max(1, height - 52)};
    const priceBottom = plot.y + plot.h * 0.76;
    this.priceHeight = priceBottom - plot.y;
    const volumeTop = priceBottom + 22;
    const bottom = plot.y + plot.h;
    const volumeHeight = Math.max(1, bottom - volumeTop);
    const step = plot.w / this.count;
    const x = index => plot.x + (index - this.left + 0.5) * step;
    const y = price => plot.y + (high - price) / (high - low) * (priceBottom - plot.y);
    this.sessionBands(first, last, x, step, plot);
    ctx.fillStyle = colors.text;
    // Nice decimal steps keep the price axis readable as the view changes.
    const rough = (high - low) / Math.max(2, Math.floor((priceBottom - plot.y) / 60));
    const power = 10 ** Math.floor(Math.log10(rough));
    const tick = [1, 2, 5, 10].find(value => value * power >= rough) * power;
    const decimals = Math.max(2, Math.min(8, -Math.floor(Math.log10(tick))));
    const firstTick = Math.ceil(low / tick);
    for (let index = 0; index < 100; index++) {
      const price = (firstTick + index) * tick;
      if (price > high) break;
      const py = y(price);
      this.line(plot.x, py, plot.x + plot.w, py, colors.grid);
      ctx.fillText(price.toFixed(decimals), plot.x + plot.w + 8, py + 4);
    }
    const timeTicks = Math.max(1, Math.floor(plot.w / (['1d', '1w'].includes(this.interval) ? 135 : 110)));
    const stride = Math.max(1, Math.ceil(this.count / timeTicks));
    const ticks = new Map();
    for (let index = Math.ceil((this.left - this.tickOffset) / stride) * stride + this.tickOffset; index < last; index += stride) {
      ticks.set(index, this.timeLabel(this.bars[index].time));
    }
    if (this.intervalSeconds()) {
      for (let index = first; index < last; index++) {
        if (index === 0 || this.day(this.bars[index].time) !== this.day(this.bars[index - 1].time)) {
          const dateLabel = this.intradayDateFormat.format(this.date(this.bars[index].time));
          for (const candidate of ticks.keys()) if (Math.abs(x(candidate) - x(index)) < 145) ticks.delete(candidate);
          ticks.set(index, dateLabel);
        }
      }
    }
    let labelEnd = -Infinity;
    for (const [index, text] of [...ticks].sort((a, b) => a[0] - b[0])) {
      const px = x(index);
      this.line(px, plot.y, px, bottom, colors.grid);
      const labelWidth = ctx.measureText(text).width;
      const labelX = Math.max(plot.x, Math.min(px - labelWidth / 2, plot.x + plot.w - labelWidth));
      if (labelX >= labelEnd + 10) {
        ctx.fillText(text, labelX, bottom + 23);
        labelEnd = labelX + labelWidth;
      }
    }
    this.line(plot.x + plot.w, plot.y, plot.x + plot.w, bottom, '#314258');
    this.line(plot.x, priceBottom + 11, plot.x + plot.w, priceBottom + 11, '#314258');
    this.line(plot.x, bottom, plot.x + plot.w, bottom, '#314258');
    ctx.fillText(this.compact.format(volumeMax), plot.x + plot.w + 8, volumeTop + 8);
    ctx.fillText('0', plot.x + plot.w + 8, bottom);
    ctx.fillText('VOLUME', plot.x + 6, volumeTop + 8);
    ctx.save();
    ctx.beginPath(); ctx.rect(plot.x, plot.y, plot.w, this.priceHeight); ctx.clip();
    const candleWidth = Math.max(1, step * 0.7);
    for (let index = first; index < last; index++) {
      const bar = this.bars[index];
      const px = x(index);
      const color = bar.close >= bar.open ? colors.up : colors.down;
      this.line(px, y(bar.high), px, y(bar.low), color);
      ctx.fillStyle = color;
      ctx.fillRect(px - candleWidth / 2, Math.min(y(bar.open), y(bar.close)), candleWidth, Math.max(1, Math.abs(y(bar.open) - y(bar.close))));
    }
    ctx.restore();
    ctx.save();
    ctx.beginPath(); ctx.rect(plot.x, volumeTop, plot.w, volumeHeight); ctx.clip();
    for (let index = first; index < last; index++) {
      const bar = this.bars[index];
      if (bar.volume == null) continue;
      const px = x(index);
      ctx.fillStyle = bar.close >= bar.open ? colors.up : colors.down;
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
      const index = Math.floor(this.left + (hover.x - plot.x) / step);
      selected = index >= first && index < last ? this.bars[index] : null;
      const px = selected ? x(index) : hover.x;
      this.line(px, plot.y, px, bottom, '#a5b9d0', [4, 4]);
      this.line(plot.x, hover.y, plot.x + plot.w, hover.y, '#a5b9d0', [4, 4]);
      const value = hover.y <= priceBottom ? this.number.format(high - (hover.y - plot.y) / (priceBottom - plot.y) * (high - low)) : this.compact.format(Math.max(0, (bottom - hover.y) / volumeHeight * volumeMax));
      this.label(value, plot.x + plot.w, hover.y - 11, '#33465d');
      if (selected) this.label(this.timeLabel(selected.time, true), px, bottom + 5, '#33465d', '#e1e8f0', 'center');
    }
    this.legend.textContent = selected ? `${this.timeLabel(selected.time, true)}   O ${this.number.format(selected.open)}   H ${this.number.format(selected.high)}   L ${this.number.format(selected.low)}   C ${this.number.format(selected.close)}   Vol ${selected.volume == null ? '—' : this.number.format(selected.volume)}` : 'No bar at this position';
  }
}

const initial = JSON.parse(document.getElementById('chart-data').textContent);
const liveEndpoint = __LIVE_ENDPOINT__;
const controlsEnabled = __CONTROLS_ENABLED__;
const historyEnabled = __HISTORY_ENABLED__;
const status = document.getElementById('status');
const error = document.getElementById('error');
const fields = document.getElementById('selection-fields');
const symbolInput = document.getElementById('symbol-input');
const intervalInput = document.getElementById('interval-input');
const durationInput = document.getElementById('duration-input');
const hoursInput = document.getElementById('hours-input');
let currentSymbol = initial.symbol;
let currentInterval = initial.interval;
let loading = false;
let selectionError = '';
let selectionId = initial.selection_id;
let historyLoading = false;
let historyError = '';
let historyNote = '';
let historyAvailable = true;
let fixedRange = initial.requested_start != null;
let generation = 0;
const olderButton = document.getElementById('load-older');
const historyStatus = document.getElementById('history-status');
function historyState() {
  olderButton.disabled = !historyEnabled || loading || historyLoading || !historyAvailable;
  olderButton.textContent = historyLoading ? 'Loading older…' : historyError ? 'Retry older history' : 'Load older';
  historyStatus.textContent = fixedRange ? 'Fixed historical range. Request a new range to extend it.' : !historyEnabled ? 'Older history needs a connected chart.' :
    historyLoading ? 'Fetching earlier bars…' : !historyAvailable ? 'No older bars returned.' : historyNote;
}
symbolInput.value = initial.symbol;
intervalInput.value = initial.interval;
durationInput.value = initial.duration || '1 D';
hoursInput.value = initial.regular_hours === false ? 'extended' : 'regular';
fields.disabled = !controlsEnabled;
if (controlsEnabled) document.getElementById('controls-note').textContent = 'US stocks and ETFs · History examples: 1 D, 2 W, 6 M · Load chart or press Enter';
const chart = new MarketChart(document.getElementById('market-canvas'), document.getElementById('legend'), initial.interval);
let currentPayload = initial;
let browserConnected = true;
function freshness(payload, now = Date.now() / 1000) {
  if (!payload.live || !liveEndpoint) return 'Snapshot';
  if (['disconnected', 'reconnecting', 'closed'].includes(payload.connection_state)) return payload.connection_state;
  const sessions = (payload.sessions || []).filter(s => s.regular === (payload.regular_hours !== false));
  if (!sessions.some(s => now >= s.start && now < s.end)) {
    return sessions.some(s => s.date === chart.day(now)) ? 'Outside requested session' : 'Session hours unverified';
  }
  const received = Date.parse(payload.last_live_update || payload.last_update || '') / 1000;
  if (Number.isFinite(received) && now - received > 90) return 'No bar callback for over 90s';
  return payload.last_live_update ? 'Receiving bar updates · Entitlements unverified' : 'Subscribed · Waiting for bar updates';
}
function updateClock(now = Date.now() / 1000) {
  const payload = currentPayload;
  const received = payload.last_update ? chart.timeLabel(Date.parse(payload.last_update) / 1000, true) : 'unavailable';
  const state = browserConnected ? freshness(payload, now) : 'Chart server unreachable';
  document.getElementById('freshness').textContent = `${state} · Last bar received: ${received}`;
  const seconds = chart.intervalSeconds();
  const latest = chart.bars.at(-1);
  let countdown = '';
  if (browserConnected && seconds && payload.live && liveEndpoint && payload.connection_state === 'subscribed') {
    const session = (payload.sessions || []).find(s => s.regular === (payload.regular_hours !== false) && now >= s.start && now < s.end);
    if (session && latest && now >= latest.time && now < Math.min(chart.barBoundary(latest.time), session.end)) {
      const remaining = Math.ceil(Math.min(chart.barBoundary(latest.time), session.end) - now);
      countdown = `Current bar boundary in ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')} · Provider confirmation may arrive later`;
    }
  }
  document.getElementById('countdown').textContent = countdown;
}
function showError(message) { error.hidden = !message; error.textContent = message || ''; }
function draw(payload, reset = false) {
  browserConnected = true;
  currentPayload = payload;
  reset = reset || payload.symbol !== currentSymbol || payload.interval !== currentInterval ||
    (payload.selection_id != null && payload.selection_id !== selectionId);
  selectionId = payload.selection_id ?? selectionId;
  fixedRange = payload.requested_start != null;
  historyAvailable = !payload.history_exhausted && !fixedRange;
  currentSymbol = payload.symbol;
  currentInterval = payload.interval;
  document.getElementById('symbol').textContent = payload.symbol;
  document.getElementById('meta').textContent = `${payload.interval} · ${payload.provider} · USD · ${payload.regular_hours === false ? 'Extended hours included' : 'Regular hours'} · New York`;
  document.title = `${payload.symbol} · PyIBQuant`;
  chart.setInterval(payload.interval);
  if (reset) {
    chart.dayCache.clear();
    chart.bars = []; chart.hover = null; chart.setAutoscale(true);
    historyError = ''; historyNote = ''; selectionError = '';
    symbolInput.value = payload.symbol;
    intervalInput.value = payload.interval;
    durationInput.value = payload.duration || '1 D';
    hoursInput.value = payload.regular_hours === false ? 'extended' : 'regular';
  }
  chart.setSessions(payload.sessions);
  chart.setData(payload.bars);
  document.getElementById('sessions-note').textContent = chart.intervalSeconds() ?
    payload.schedule_error || (chart.sessions.length ? 'Shaded: outside IBKR regular sessions · Dashed: New York date boundaries' : 'Session schedule unavailable; shading omitted.') : '';
  status.textContent = `${payload.status} · ${payload.bars.length.toLocaleString()} bars${payload.live && liveEndpoint ? ' · Updates checked every 2s' : ''}`;
  showError([selectionError, historyError, payload.error, ...(payload.warnings || [])].filter(Boolean).join('\n'));
  historyState();
  updateClock();
}
draw(initial);
async function loadOlder() {
  if (!historyEnabled || loading || historyLoading || !historyAvailable || !chart.bars.length) return;
  const started = ++generation;
  const before = chart.bars[0].time;
  historyLoading = true;
  historyError = '';
  fields.disabled = true;
  historyState();
  try {
    const response = await fetch('/older', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({selection_id: selectionId, before})});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Chart server returned ${response.status}`);
    if (started === generation) {
      const previous = chart.bars.length;
      draw(payload);
      const added = Math.max(0, chart.bars.length - previous);
      const source = payload.history_cache_hit ? ' from cache' : '';
      historyNote = added ? `Added ${added.toLocaleString()} earlier bars${source}. Pan left to explore.` : `History checked${source}.`;
    }
  } catch (e) {
    if (started === generation) {
      historyError = `Older history: ${e.message} Use Retry older history to try again.`;
      showError(historyError);
    }
  } finally {
    historyLoading = false;
    fields.disabled = !controlsEnabled || loading;
    historyState();
  }
}
chart.onOlder = () => { if (!historyError) loadOlder(); };
olderButton.onclick = loadOlder;
const autoscale = document.getElementById('autoscale');
chart.onScaleChange = () => {
  const automatic = chart.manualRange === null;
  autoscale.setAttribute('aria-pressed', String(automatic));
  autoscale.textContent = `Autoscale: ${automatic ? 'on' : 'off'}`;
};
autoscale.onclick = () => chart.setAutoscale(chart.manualRange !== null);
document.getElementById('right-margin').onchange = event => chart.setRightMargin(Number(event.target.value));
document.getElementById('fit').onclick = () => chart.fit();
document.getElementById('latest').onclick = () => chart.latest();
document.getElementById('sessions').onclick = event => {
  chart.showSessions = !chart.showSessions;
  event.target.setAttribute('aria-pressed', String(chart.showSessions));
  event.target.textContent = `Sessions: ${chart.showSessions ? 'on' : 'off'}`;
  chart.requestDraw();
};
document.getElementById('chart-controls').addEventListener('submit', async event => {
  event.preventDefault();
  if (!controlsEnabled || loading || historyLoading) return;
  const selection = {symbol: symbolInput.value.trim().toUpperCase(), interval: intervalInput.value, duration: durationInput.value.trim(), regular_hours: hoursInput.value === 'regular'};
  loading = true;
  historyState();
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
    historyState();
  }
});
async function poll() {
  const started = generation;
  try {
    if (loading || historyLoading) return;
    const response = await fetch('/data', {cache: 'no-store'});
    if (!response.ok) throw new Error(`Chart server returned ${response.status}`);
    const payload = await response.json();
    if (!loading && started === generation) draw(payload);
  } catch (e) {
    if (!loading && started === generation) {
      browserConnected = false;
      updateClock();
      status.textContent = 'Chart connection interrupted';
      showError(`${e.message}. Keep the Python process running; retrying…`);
    }
  } finally { setTimeout(poll, 2000); }
}
if (liveEndpoint) setTimeout(poll, 2000);
if (liveEndpoint) setInterval(() => updateClock(), 1000);
