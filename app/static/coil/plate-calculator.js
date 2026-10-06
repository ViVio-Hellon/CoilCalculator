/**
 * 平板重量計算ツール
 * 平板の寸法 A・B と板厚から、面積・体積・重量を計算する(コイル計算と同じ仕組み)
 *
 *   面積(mm²) = A × B            面積(m²)  = 面積(mm²) / 1,000,000
 *   体積(mm³) = A × B × 板厚      体積(cm³) = 体積(mm³) / 1000
 *   重量(g)   = 体積(cm³) × 比重   重量(kg)  = 重量(g) / 1000
 *
 * 計算・範囲の確かめ・丸め・画面に出す文字は Python(coilcalc/calc.py)が持つ。
 * ここは欄の文字を送って(app-shell.js)、返ってきた文字を置くだけ。
 */

class PlateCalculator {
  /**
   * 計算機クラスを初期化
   */
  constructor() {
    this.initializeElements();

    // グローバル参照を追加(グラフ・3D から使う)
    window.plateCalculator = this;

    this.setupEventListeners();
    this.calculate();
  }

  /**
   * 要素の参照を取得
   */
  initializeElements() {
    const $ = (id) => document.getElementById(id);
    this.section = $('plate-section');

    this.aInput = $('plate-a');
    this.bInput = $('plate-b');
    this.tInput = $('plate-t');
    this.specificGravityInput = $('plate-specific-gravity');
    this.materialPreset = $('plate-material-preset');

    this.aError = $('plate-a-error');
    this.bError = $('plate-b-error');
    this.tError = $('plate-t-error');
    this.specificGravityError = $('plate-specific-gravity-error');

    this.weightResult = $('plate-weight-result');
    this.areaResult = $('plate-area-result');
    this.volumeResult = $('plate-volume-result');
  }

  /**
   * 各種イベントリスナーを設定
   */
  setupEventListeners() {
    // 平板のタブ切り替え(コイルのタブとは別の名前にして、互いに影響しないようにする)
    const tabs = this.section.querySelectorAll('.ptab');
    const tabContents = this.section.querySelectorAll('.ptab-content');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(content => content.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.getAttribute('data-ptab')).classList.add('active');
      });
    });

    // モーダル(開く・閉じる)は aluminum-coil-calculator.js が .details-btn / .modal を
    // まとめて扱っている(平板のモーダルも同じ部品)ので、ここでは繋がない

    // 材質プリセット
    this.materialPreset.addEventListener('change', () => {
      const selectedOption = this.materialPreset.options[this.materialPreset.selectedIndex];
      this.specificGravityInput.value = selectedOption.getAttribute('data-gravity');
      this.calculate();
    });

    // 入力フィールド(範囲の確かめも計算も Python がする)
    for (const [input] of Object.values(this.fields())) {
      input.addEventListener('input', () => this.calculate());
    }
  }

  /**
   * 欄の名前(Python の coilcalc/calc.py の PLATE_FIELDS)→ [入力欄, エラーの文]
   */
  fields() {
    return {
      'a': [this.aInput, this.aError],
      'b': [this.bInput, this.bError],
      't': [this.tInput, this.tError],
      'specific-gravity': [this.specificGravityInput, this.specificGravityError]
    };
  }

  /**
   * 範囲の外の欄を赤くする(どの欄が外かは Python が決める)
   * @param {string[]} invalid
   */
  showInvalid(invalid) {
    for (const [name, [input, errorElement]] of Object.entries(this.fields())) {
      const bad = invalid.includes(name);
      input.classList.toggle('error', bad);
      errorElement.style.display = bad ? 'block' : 'none';
    }
  }

  /**
   * 計算を Python に頼んで、返ってきた文字を置く。
   * 範囲の外の欄があるあいだは計算しない(結果・3D・グラフは前のまま)。
   */
  async calculate() {
    const raw = {};
    for (const [name, [input]] of Object.entries(this.fields())) raw[name] = input.value;
    const body = await window.AppShell.calc('plate', raw);
    if (!body) return;
    this.showInvalid(body.invalid);
    document.dispatchEvent(new CustomEvent('calc-validated', { detail: { shape: 'plate', ok: body.ok } }));
    if (!body.ok) return;
    this.last = body;

    // 結果値・詳細計算過程・モーダル(文字は Python が組み立てたまま)
    this.weightResult.textContent = body.results.weight;
    this.areaResult.textContent = body.results.area;
    this.volumeResult.textContent = body.results.volume;
    for (const [id, lines] of Object.entries(body.details)) {
      document.getElementById(id).replaceChildren(...CoilCalculator.lines(lines));
    }
    for (const [id, text] of Object.entries(body.modal)) {
      document.getElementById(id).textContent = text;
    }

    // 3D・グラフへ知らせる(3D は a・b・t を使う)
    const v = body.values;
    document.dispatchEvent(new CustomEvent('plate-calculated', {
      detail: { ...body, a: v.a, b: v.b, t: v.t, specificGravity: v['specific-gravity'] }
    }));
  }
}

// アプリケーションを初期化
document.addEventListener('DOMContentLoaded', () => {
  new PlateCalculator();
});
