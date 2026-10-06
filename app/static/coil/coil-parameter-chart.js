/**
 * アルミニウムコイルパラメータグラフ
 * 入力パラメータと計算結果の関係を視覚化するグラフ機能
 *
 * 線の点(X 軸の欄だけを範囲いっぱいに動かした計算)は Python が計算の答えと一緒に
 * 返す(coilcalc/calc.py の _coil_chart)。ここは描くだけ。計算のたびに線を描き直す
 * (ほかの欄が変われば線の形も変わるため。平板のグラフと同じ動き)。
 */
class CoilParameterChart {
    /**
     * グラフ機能の初期化
     */
    constructor() {
        // チャート要素の参照
        this.chartCanvas = document.getElementById('parameter-chart');
        if (!this.chartCanvas) {
            console.error('Chart canvas element not found');
            return;
        }

        // 軸選択要素
        this.xAxisSelect = document.getElementById('x-axis-param');
        this.yAxisSelect = document.getElementById('y-axis-result');

        // X 軸の見出しと単位(範囲と点は Python の答えの chart にある)
        this.paramRanges = {
            'thickness': { min: 0, max: 600, unit: 'mm', label: '肉厚' },
            'inner-diameter': { min: 250, max: 610, unit: 'mm', label: '内径' },
            'coil-width': { min: 0, max: 1800, unit: 'mm', label: 'コイル幅' },
            'plate-thickness': { min: 0.05, max: 20, unit: 'mm', label: '板厚' }
        };
        
        // 結果タイプの定義
        this.resultTypes = {
            'weight': { unit: 'kg', label: '重量', color: 'rgba(66, 133, 244, 0.7)' },
            'length': { unit: 'm', label: '長さ', color: 'rgba(15, 157, 88, 0.7)' },
            'windings': { unit: '巻', label: '巻き数', color: 'rgba(219, 68, 55, 0.7)' }
        };
        
        // デフォルト選択
        this.selectedXParam = 'thickness';
        this.selectedYResult = 'weight';
        
        // Chart.js インスタンス
        this.chart = null;
        
        // いちばん新しい計算の答え(線の点・いまの値)
        this.latest = window.coilCalculator ? window.coilCalculator.last : null;
        
        // イベントリスナーの設定
        this.setupEventListeners();
        
        // 初期グラフの描画
        this.initializeChart();
        this.updateChart();
    }
    
    /**
     * イベントリスナーを設定
     */
    setupEventListeners() {
        // 軸パラメータ選択変更時
        this.xAxisSelect.addEventListener('change', () => {
            this.selectedXParam = this.xAxisSelect.value;
            this.updateChart();
        });
        
        this.yAxisSelect.addEventListener('change', () => {
            this.selectedYResult = this.yAxisSelect.value;
            this.updateChart();
        });
        
        // 計算の答えが届いたら線と現在値を描き直す(範囲の外の欄があるあいだは届かない)
        document.addEventListener('coil-calculated', (event) => {
            this.latest = event.detail;
            this.updateChart();
        });
    }
    
    /**
     * グラフ初期化
     */
    initializeChart() {
        // Chart.jsが読み込まれているか確認
        if (typeof Chart === 'undefined') {
            console.error('Chart.js library is not loaded!');
            return;
        }
        
        const ctx = this.chartCanvas.getContext('2d');
        
        // 現在選択されているパラメータの範囲を取得
        const paramRange = this.paramRanges[this.selectedXParam];
        
        // グラフ設定
        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: '',
                    data: [],
                    borderColor: this.resultTypes[this.selectedYResult].color,
                    backgroundColor: this.resultTypes[this.selectedYResult].color.replace('0.7', '0.1'),
                    borderWidth: 2,
                    tension: 0.2,
                    fill: true,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            title: (tooltipItems) => {
                                const xValue = tooltipItems[0].parsed.x;
                                const paramInfo = this.paramRanges[this.selectedXParam];
                                return `${paramInfo.label}: ${xValue} ${paramInfo.unit}`;
                            },
                            label: (tooltipItem) => {
                                const resultInfo = this.resultTypes[this.selectedYResult];
                                return `${resultInfo.label}: ${tooltipItem.parsed.y.toFixed(1)} ${resultInfo.unit}`;
                            }
                        }
                    },
                    legend: {
                        display: false
                    },
                    annotation: {
                        annotations: {
                            currentValue: {
                                type: 'line',
                                xMin: 0,
                                xMax: 0,
                                borderColor: 'rgba(255, 99, 132, 0.8)',
                                borderWidth: 2,
                                borderDash: [5, 5],
                                label: {
                                    display: true,
                                    content: '現在値',
                                    position: 'start'
                                }
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: paramRange.min,
                        max: paramRange.max,
                        title: {
                            display: true,
                            text: this.paramRanges[this.selectedXParam].label + ' (' + this.paramRanges[this.selectedXParam].unit + ')'
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        },
                        ticks: {
                            callback: (value) => {
                                // パラメータタイプに応じてフォーマットを変更
                                if (this.selectedXParam === 'plate-thickness') {
                                    // 板厚の場合のみ小数点以下最大2桁表示
                                    return Number.isInteger(value) ? value : value.toFixed(2);
                                } else {
                                    // その他のパラメータ（肉厚、内径、コイル幅）は整数表示
                                    return Math.round(value);
                                }
                            },
                            // 目盛りの数を制限して表示を見やすくする
                            maxTicksLimit: 10
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: this.resultTypes[this.selectedYResult].label + ' (' + this.resultTypes[this.selectedYResult].unit + ')'
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        },
                        beginAtZero: true
                    }
                },
                interaction: {
                    mode: 'index',
                    intersect: false
                }
            }
        });
    }
    
    /**
     * グラフデータ(Python の答えの chart から、いま選んでいる軸の分を取り出す)
     * @returns {Object|null} グラフデータ
     */
    generateChartData() {
        if (!this.latest || !this.latest.chart) return null;
        const line = this.latest.chart[this.selectedXParam];
        return {
            labels: line.labels,
            data: line.series[this.selectedYResult],
            min: line.min,
            max: line.max
        };
    }
    
    /**
     * グラフを更新
     */
    updateChart() {
        // チャートが初期化されているか確認
        if (!this.chart) {
            console.warn('Chart is not initialized yet.');
            return;
        }
        
        // グラフデータを取り出す(まだ答えが無ければ描かない)
        const chartData = this.generateChartData();
        if (!chartData) return;
        const { labels, data } = chartData;
        
        // グラフタイトルを更新
        const xParamInfo = this.paramRanges[this.selectedXParam];
        const yResultInfo = this.resultTypes[this.selectedYResult];
        
        // スケールタイトルを更新
        this.chart.options.scales.x.title.text = xParamInfo.label + ' (' + xParamInfo.unit + ')';
        this.chart.options.scales.y.title.text = yResultInfo.label + ' (' + yResultInfo.unit + ')';
        
        // X軸の範囲を選択されたパラメータに合わせて設定(範囲の正は Python)
        this.chart.options.scales.x.min = chartData.min;
        this.chart.options.scales.x.max = chartData.max;
        
        // X軸の目盛り表示を更新
        // パラメータタイプに応じたフォーマットでTicksを表示
        this.chart.options.scales.x.ticks.callback = (value) => {
            if (this.selectedXParam === 'plate-thickness') {
                // 板厚の場合のみ小数点以下最大2桁表示
                return Number.isInteger(value) ? value : value.toFixed(2);
            } else {
                // その他のパラメータ（肉厚、内径、コイル幅）は整数表示
                return Math.round(value);
            }
        };
        
        // データセット更新
        this.chart.data.labels = labels;
        this.chart.data.datasets[0].data = data;
        this.chart.data.datasets[0].label = yResultInfo.label;
        this.chart.data.datasets[0].borderColor = yResultInfo.color;
        this.chart.data.datasets[0].backgroundColor = yResultInfo.color.replace('0.7', '0.1');
        
        // 現在値マーカーを更新
        this.updateChartMarker();
        
        // グラフ再描画
        this.chart.update();
    }
    
    /**
     * 現在値マーカーを更新
     */
    updateChartMarker() {
        // 現在の入力値を取得(Python が欄の文字から読んだ数)
        const currentValue = this.latest && this.latest.values
            ? this.latest.values[this.selectedXParam] : NaN;
        
        // 無効な値の場合は更新をスキップ
        if (currentValue === null || isNaN(currentValue)) {
            console.warn('現在値が無効です:', currentValue);
            return;
        }
        
        // アノテーションプラグインが利用可能か確認
        if (!this.chart.options.plugins) {
            this.chart.options.plugins = {};
        }
        
        if (!this.chart.options.plugins.annotation) {
            this.chart.options.plugins.annotation = {};
        }
        
        if (!this.chart.options.plugins.annotation.annotations) {
            this.chart.options.plugins.annotation.annotations = {};
        }
        
        // 現在値のラインアノテーションを設定
        this.chart.options.plugins.annotation.annotations.currentValue = {
            type: 'line',
            scaleID: 'x',
            value: currentValue,
            borderColor: 'rgba(255, 99, 132, 0.8)',
            borderWidth: 2,
            borderDash: [5, 5],
            label: {
                display: true,
                content: '現在値',
                position: 'top',
                backgroundColor: 'rgba(255, 99, 132, 0.8)',
                font: {
                    size: 12,
                    weight: 'bold'
                }
            }
        };
        
        // アノテーションの値をコンソールに表示（デバッグ用）
        // console.log(`マーカー更新: ${this.selectedXParam} = ${currentValue}`);
        
        // グラフ更新
        if (this.chart) {
            this.chart.update();
        }
    }
}

// ページ読み込み時にグラフ機能を初期化(aluminum-coil-calculator.js より後に読む)
document.addEventListener('DOMContentLoaded', () => {
    if (typeof Chart === 'undefined') {
        // Chart.js はアプリに同梱している(app/static/vendor/chartjs/)。インターネットからは
        // 読み込まない(ラインPCは外に出られない・アプリの CSP も外のスクリプトを断る)
        console.error('Chart.js library is not loaded.');
    } else {
        window.coilParameterChart = new CoilParameterChart();
    }
});
