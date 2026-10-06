/**
 * アルミニウムコイル重量・長さ計算ツール
 * コイルの肉厚、内径、幅から重量、長さ、巻き数を計算するツール
 *
 * 計算・範囲の確かめ・丸め・画面に出す文字は Python(coilcalc/calc.py)が持つ。
 * ここは欄の文字を送って(app-shell.js)、返ってきた文字を置くだけ。
 */

class CoilCalculator {
  /**
   * 計算機クラスを初期化
   */
  constructor() {
    // DOM要素の参照を取得
    this.initializeInputElements();
    this.initializeErrorElements();
    this.initializeResultElements();

    // グローバル参照を追加
    window.coilCalculator = this;

    // イベントリスナーを設定
    this.setupEventListeners();

    // 初期計算を実行
    this.calculate();
  }

  /**
   * 入力フィールド要素の参照を取得
   */
  initializeInputElements() {
    this.thicknessInput = document.getElementById('thickness');
    this.innerDiameterInput = document.getElementById('inner-diameter');
    this.coilWidthInput = document.getElementById('coil-width');
    this.specificGravityInput = document.getElementById('specific-gravity');
    this.plateThicknessInput = document.getElementById('plate-thickness');
    this.materialPreset = document.getElementById('material-preset');
  }

  /**
   * エラーメッセージ要素の参照を取得
   */
  initializeErrorElements() {
    this.thicknessError = document.getElementById('thickness-error');
    this.innerDiameterError = document.getElementById('inner-diameter-error');
    this.coilWidthError = document.getElementById('coil-width-error');
    this.specificGravityError = document.getElementById('specific-gravity-error');
    this.plateThicknessError = document.getElementById('plate-thickness-error');
  }

  /**
   * 結果表示要素の参照を取得
   */
  initializeResultElements() {
    this.weightResult = document.getElementById('weight-result');
    this.lengthResult = document.getElementById('length-result');
    this.windingsResult = document.getElementById('windings-result');
  }

  /**
   * 各種イベントリスナーを設定
   */
  setupEventListeners() {
    // タブ切り替え
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
      tab.addEventListener('click', function() {
        const tabId = this.getAttribute('data-tab');
        
        // すべてのタブからactiveクラスを削除
        tabs.forEach(t => t.classList.remove('active'));
        // すべてのタブコンテンツからactiveクラスを削除
        tabContents.forEach(content => content.classList.remove('active'));
        
        // クリックしたタブとそれに対応するコンテンツにactiveクラスを追加
        this.classList.add('active');
        document.getElementById(tabId).classList.add('active');
      });
    });

    // モーダル管理
    const detailButtons = document.querySelectorAll('.details-btn');
    const modalCloseButtons = document.querySelectorAll('.modal-close');
    const modals = document.querySelectorAll('.modal');

    detailButtons.forEach(button => {
      button.addEventListener('click', function() {
        const modalId = this.getAttribute('data-modal');
        document.getElementById(modalId).classList.add('show');
      });
    });

    modalCloseButtons.forEach(button => {
      button.addEventListener('click', () => {
        const modal = button.closest('.modal');
        modal.classList.remove('show');
      });
    });

    // モーダルの外側をクリックした時にモーダルを閉じる
    modals.forEach(modal => {
      modal.addEventListener('click', function(event) {
        if (event.target === this) {
          this.classList.remove('show');
        }
      });
    });

    // 材質プリセットのイベントリスナー
    this.materialPreset.addEventListener('change', () => {
      const selectedOption = this.materialPreset.options[this.materialPreset.selectedIndex];
      this.specificGravityInput.value = selectedOption.getAttribute('data-gravity');
      
      // 計算を更新
      this.calculate();
    });

    // 入力フィールドのイベントリスナー(範囲の確かめも計算も Python がする)
    for (const [input] of Object.values(this.fields())) {
      input.addEventListener('input', () => this.calculate());
    }
  }

  /**
   * 欄の名前(Python の coilcalc/calc.py の COIL_FIELDS)→ [入力欄, エラーの文]
   */
  fields() {
    return {
      'thickness': [this.thicknessInput, this.thicknessError],
      'inner-diameter': [this.innerDiameterInput, this.innerDiameterError],
      'coil-width': [this.coilWidthInput, this.coilWidthError],
      'specific-gravity': [this.specificGravityInput, this.specificGravityError],
      'plate-thickness': [this.plateThicknessInput, this.plateThicknessError]
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
   * 範囲の外の欄があるあいだは計算しない(結果は前のまま)。
   */
  async calculate() {
    const raw = {};
    for (const [name, [input]] of Object.entries(this.fields())) raw[name] = input.value;
    const body = await window.AppShell.calc('coil', raw);
    if (!body) return;
    this.showInvalid(body.invalid);
    if (body.ok) {
      this.render(body);
      this.last = body;
    }
    document.dispatchEvent(new CustomEvent('calc-validated', { detail: { shape: 'coil', ok: body.ok } }));
    if (body.ok) {
      document.dispatchEvent(new CustomEvent('coil-calculated', { detail: body }));
    }
  }

  /**
   * 結果・詳細計算過程・モーダルを置く(文字は Python が組み立てたまま)
   */
  render(body) {
    this.weightResult.textContent = body.results.weight;
    this.lengthResult.textContent = body.results.length;
    this.windingsResult.textContent = body.results.windings;
    for (const [id, lines] of Object.entries(body.details)) {
      document.getElementById(id).replaceChildren(...CoilCalculator.lines(lines));
    }
    for (const [id, text] of Object.entries(body.modal)) {
      document.getElementById(id).textContent = text;
    }
  }

  /**
   * 計算の経過の行(`式 = <span class="value">値</span>`)。最後の行以外は下を空ける
   * @param {{text: string, value: string}[]} lines
   */
  static lines(lines) {
    return lines.map((line, i) => {
      const div = document.createElement('div');
      if (i < lines.length - 1) div.className = 'mb-2';
      div.append(line.text);
      const span = document.createElement('span');
      span.className = 'value';
      span.textContent = line.value;
      div.append(span);
      return div;
    });
  }
}

// アプリケーションを初期化
document.addEventListener('DOMContentLoaded', () => {
  new CoilCalculator();
});