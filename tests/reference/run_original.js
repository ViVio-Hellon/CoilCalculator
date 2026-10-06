/*
  run_original.js — 移す前の JS(original_js/)を**そのまま**動かして、画面に出ていた文字を集める

  tests/test_js_equivalence.py が使う。標準入力に入力の組(JSON)を受け取り、
  元の JS が画面に書いた文字・グラフの点を標準出力に JSON で返す。
  ブラウザは使わない。元の JS が触る分だけの小さな document を用意して、
  元のクラスの calculate() / generateChartData() をそのまま呼ぶ。
*/
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const DIR = path.join(__dirname, 'original_js');

// ---- 元の JS が触る分だけの DOM -------------------------------------------
class FakeClassList {
  constructor() { this.set = new Set(); }
  add(c) { this.set.add(c); }
  remove(c) { this.set.delete(c); }
  contains(c) { return this.set.has(c); }
  toggle(c, on) { if (on === undefined ? !this.set.has(c) : on) this.set.add(c); else this.set.delete(c); }
}

class FakeElement {
  constructor(id) {
    this.id = id;
    this.value = '';
    this.children = [];
    this._text = null;
    this.innerHTML = '';
    this.className = '';
    this.classList = new FakeClassList();
    this.style = {};
    this.options = [];
    this.selectedIndex = 0;
  }
  addEventListener() {}
  querySelectorAll() { return []; }
  append(...items) { for (const x of items) this.children.push(x); }
  replaceChildren(...items) { this.children = items; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() {
    if (this._text !== null && this.children.length === 0) return this._text;
    return this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join('');
  }
}

function makeDocument() {
  const elements = new Map();
  const events = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new FakeElement(id));
      return elements.get(id);
    },
    querySelectorAll() { return []; },
    addEventListener() {},
    createElement() { return new FakeElement(''); },
    dispatchEvent(e) { events.push(e); },
  };
  return { document, elements, events };
}

function load(names, extra) {
  const { document, elements, events } = makeDocument();
  const context = {
    document,
    window: {},
    console,
    Math,
    Number,
    String,
    Object,
    isNaN,
    parseFloat,
    setTimeout: () => 0,
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    ...extra,
  };
  vm.createContext(context);
  let code = names.map((n) => fs.readFileSync(path.join(DIR, n), 'utf8')).join('\n');
  // クラスを外から使えるようにする(class 宣言は context の持ち物にならないため)
  code += '\n;this.__classes = { ' + extra.__export.join(', ') + ' };';
  vm.runInContext(code, context);
  return { context, document, elements, events, classes: context.__classes };
}

// ---- 画面に書かれた文字を読む ----------------------------------------------
/** 元のコイルの詳細計算過程は innerHTML。`式 = <span class="value">値</span>` を行ごとに分ける */
function linesFromHtml(html) {
  const out = [];
  const re = /<div[^>]*>([\s\S]*?)<span class="value">([\s\S]*?)<\/span><\/div>/g;
  let m;
  while ((m = re.exec(html)) !== null) out.push({ text: m[1], value: m[2] });
  return out;
}

/** 元の平板の詳細計算過程は DOM の行(`div` に 文字 + `span.value`) */
function linesFromNodes(el) {
  return el.children.map((div) => ({
    text: div.children.filter((c) => typeof c === 'string').join(''),
    value: div.children.filter((c) => typeof c !== 'string').map((c) => c.textContent).join(''),
  }));
}

// ---- コイル ----------------------------------------------------------------
const COIL_IDS = ['thickness', 'inner-diameter', 'coil-width', 'specific-gravity', 'plate-thickness'];
const COIL_RANGES = {
  'thickness': [0, 600], 'inner-diameter': [250, 610], 'coil-width': [0, 1800],
  'specific-gravity': [0.01, 100], 'plate-thickness': [0.05, 20],
};
const COIL_DETAILS = ['dimensions-detailed', 'volume-detailed', 'weight-detailed', 'length-detailed', 'windings-detailed'];
const COIL_MODAL = ['modal-large-radius', 'modal-small-radius', 'modal-large-volume', 'modal-small-volume',
  'modal-coil-volume', 'modal-coil-volume-cm', 'modal-weight-g', 'modal-weight-kg', 'modal-cross-section',
  'modal-length-area', 'modal-length-mm', 'modal-length-m', 'modal-windings'];

function runCoil(cases) {
  const env = load(['aluminum-coil-calculator.js', 'coil-parameter-chart.js'],
    { __export: ['CoilCalculator', 'CoilParameterChart'] });
  const { CoilCalculator, CoilParameterChart } = env.classes;
  const $ = (id) => env.document.getElementById(id);
  // 材質プリセット(コンストラクタが触る)
  $('material-preset').options = [{ getAttribute: () => '2.70' }];
  for (const id of COIL_IDS) $(id).value = '1';
  const calc = new CoilCalculator();

  return cases.map((fields) => {
    for (const id of COIL_IDS) $(id).value = fields[id];
    // 範囲の確かめ(元の validateInput をそのまま)
    const invalid = COIL_IDS.filter((id) => {
      const [lo, hi] = COIL_RANGES[id];
      return !calc.validateInput($(id), lo, hi, $(id + '-error'));
    });
    const out = { invalid };
    if (invalid.length) return out;
    calc.calculate();
    out.results = {
      weight: $('weight-result').textContent,
      length: $('length-result').textContent,
      windings: $('windings-result').textContent,
    };
    out.details = {};
    for (const id of COIL_DETAILS) out.details[id] = linesFromHtml($(id).innerHTML);
    out.modal = {};
    for (const id of COIL_MODAL) out.modal[id] = $(id).textContent;
    // グラフ(元の generateChartData を、いまの欄の値でそのまま)
    out.chart = {};
    const chart = Object.create(CoilParameterChart.prototype);
    chart.paramRanges = {
      'thickness': { min: 0, max: 600 }, 'inner-diameter': { min: 250, max: 610 },
      'coil-width': { min: 0, max: 1800 }, 'plate-thickness': { min: 0.05, max: 20 },
    };
    chart.thicknessInput = $('thickness');
    chart.innerDiameterInput = $('inner-diameter');
    chart.coilWidthInput = $('coil-width');
    chart.specificGravityInput = $('specific-gravity');
    chart.plateThicknessInput = $('plate-thickness');
    for (const x of Object.keys(chart.paramRanges)) {
      chart.selectedXParam = x;
      const series = {};
      let labels;
      for (const y of ['weight', 'length', 'windings']) {
        chart.selectedYResult = y;
        const d = chart.generateChartData();
        labels = d.labels;
        series[y] = d.data;
      }
      out.chart[x] = { labels, series };
    }
    return out;
  });
}

// ---- 平板 ------------------------------------------------------------------
const PLATE_IDS = { 'a': 'plate-a', 'b': 'plate-b', 't': 'plate-t', 'specific-gravity': 'plate-specific-gravity' };
const PLATE_DETAILS = ['plate-area-detailed', 'plate-volume-detailed', 'plate-weight-detailed'];
const PLATE_MODAL = ['plate-modal-volume-mm', 'plate-modal-volume-cm', 'plate-modal-weight-g', 'plate-modal-weight-kg',
  'plate-modal-area-mm', 'plate-modal-area-m', 'plate-modal-volume-mm2', 'plate-modal-volume-cm2'];

function runPlate(cases) {
  const env = load(['plate-calculator.js', 'plate-parameter-chart.js'],
    { __export: ['PlateCalculator', 'PlateParameterChart'] });
  const { PlateCalculator, PlateParameterChart } = env.classes;
  env.context.PlateCalculator = PlateCalculator;
  const $ = (id) => env.document.getElementById(id);
  $('plate-section').querySelectorAll = () => [];
  for (const id of Object.values(PLATE_IDS)) $(id).value = '1';
  const calc = new PlateCalculator();
  const rangeKey = { 'a': 'a', 'b': 'b', 't': 't', 'specific-gravity': 'specificGravity' };

  return cases.map((fields) => {
    for (const [k, id] of Object.entries(PLATE_IDS)) $(id).value = fields[k];
    const invalid = Object.keys(PLATE_IDS).filter((k) =>
      !calc.validateInput($(PLATE_IDS[k]), calc.ranges[rangeKey[k]], $(PLATE_IDS[k] + '-error')));
    const out = { invalid };
    if (invalid.length) return out;
    env.events.length = 0;
    calc.calculate();
    out.results = {
      weight: $('plate-weight-result').textContent,
      area: $('plate-area-result').textContent,
      volume: $('plate-volume-result').textContent,
    };
    out.details = {};
    for (const id of PLATE_DETAILS) out.details[id] = linesFromNodes($(id));
    out.modal = {};
    for (const id of PLATE_MODAL) out.modal[id] = $(id).textContent;
    const event = env.events.find((e) => e.type === 'plate-calculated');
    out.event = event ? { a: event.detail.a, b: event.detail.b, t: event.detail.t } : null;
    out.chart = {};
    const chart = Object.create(PlateParameterChart.prototype);
    chart.paramRanges = { a: calc.ranges.a, b: calc.ranges.b, t: calc.ranges.t };
    chart.resultTypes = { weight: { key: 'weightKg' }, area: { key: 'areaM' }, volume: { key: 'volumeCm' } };
    const current = calc.currentValues();
    for (const x of ['a', 'b', 't']) {
      chart.selectedXParam = x;
      const series = {};
      let labels;
      for (const y of ['weight', 'area', 'volume']) {
        chart.selectedYResult = y;
        const d = chart.generateChartData(current);
        labels = d.map((p) => p.x);
        series[y] = d.map((p) => p.y);
      }
      out.chart[x] = { labels, series };
    }
    return out;
  });
}

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ coil: runCoil(input.coil), plate: runPlate(input.plate) }));
