/**
 * 平板パラメータグラフ
 * 入力パラメータと計算結果の関係を視覚化する(coil-parameter-chart.js と同じ仕組み)
 *
 * 線の点は Python が計算の答えと一緒に返す(coilcalc/calc.py の _plate_chart)。
 * ここは描くだけ。
 */
class PlateParameterChart {
    constructor() {
        this.chartCanvas = document.getElementById('plate-parameter-chart');
        if (!this.chartCanvas) {
            console.error('Chart canvas element not found');
            return;
        }

        this.xAxisSelect = document.getElementById('plate-x-axis-param');
        this.yAxisSelect = document.getElementById('plate-y-axis-result');

        // X 軸の見出しと単位(範囲と点は Python の答えの chart にある)
        this.paramRanges = {
            'a': { unit: 'mm', label: 'A' },
            'b': { unit: 'mm', label: 'B' },
            't': { unit: 'mm', label: '板厚' }
        };

        // 結果タイプ
        this.resultTypes = {
            'weight': { unit: 'kg', label: '重量', color: 'rgba(66, 133, 244, 0.7)' },
            'area': { unit: 'm²', label: '面積', color: 'rgba(15, 157, 88, 0.7)' },
            'volume': { unit: 'cm³', label: '体積', color: 'rgba(219, 68, 55, 0.7)' }
        };

        this.selectedXParam = this.xAxisSelect.value;
        this.selectedYResult = this.yAxisSelect.value;
        this.chart = null;
        // いちばん新しい計算の答え(線の点・いまの値)
        this.latest = window.plateCalculator ? window.plateCalculator.last : null;

        this.setupEventListeners();
        this.initializeChart();
        this.updateChart();
    }

    setupEventListeners() {
        this.xAxisSelect.addEventListener('change', () => {
            this.selectedXParam = this.xAxisSelect.value;
            this.updateChart();
        });
        this.yAxisSelect.addEventListener('change', () => {
            this.selectedYResult = this.yAxisSelect.value;
            this.updateChart();
        });
        // 計算のたびに線と現在値を描き直す(ほかの入力が変われば線の形も変わるため)
        document.addEventListener('plate-calculated', (event) => {
            this.latest = event.detail;
            this.updateChart();
        });
    }

    initializeChart() {
        if (typeof Chart === 'undefined') {
            console.error('Chart.js library is not loaded!');
            return;
        }
        const ctx = this.chartCanvas.getContext('2d');
        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: '',
                    data: [],
                    borderWidth: 2,
                    tension: 0,
                    fill: true,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                parsing: false,
                plugins: {
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            title: (items) => {
                                const p = this.paramRanges[this.selectedXParam];
                                return `${p.label}: ${this.formatX(items[0].parsed.x)} ${p.unit}`;
                            },
                            label: (item) => {
                                const r = this.resultTypes[this.selectedYResult];
                                return `${r.label}: ${this.formatY(item.parsed.y)} ${r.unit}`;
                            }
                        }
                    },
                    legend: { display: false },
                    annotation: { annotations: {} }
                },
                scales: {
                    x: {
                        type: 'linear',
                        title: { display: true, text: '' },
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        ticks: { callback: (value) => this.formatX(value), maxTicksLimit: 10 }
                    },
                    y: {
                        title: { display: true, text: '' },
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        beginAtZero: true
                    }
                },
                interaction: { mode: 'index', intersect: false }
            }
        });
    }

    formatX(value) {
        return this.selectedXParam === 't'
            ? (Number.isInteger(value) ? value : Number(value).toFixed(2))
            : Math.round(value);
    }

    formatY(value) {
        const digits = { weight: 2, area: 3, volume: 1 }[this.selectedYResult];
        return Number(value).toFixed(digits);
    }

    /**
     * いまの入力を元に、X軸のパラメータだけを動かした点(Python の答えから取り出す)
     */
    generateChartData(line) {
        const ys = line.series[this.selectedYResult];
        return line.labels.map((x, i) => ({ x, y: ys[i] }));
    }

    updateChart() {
        if (!this.chart) return;
        // 範囲外の値があるあいだは答えが届かないので、描き直さない
        if (!this.latest || !this.latest.chart) return;
        const line = this.latest.chart[this.selectedXParam];

        const xInfo = this.paramRanges[this.selectedXParam];
        const yInfo = this.resultTypes[this.selectedYResult];
        const options = this.chart.options;
        options.scales.x.title.text = `${xInfo.label} (${xInfo.unit})`;
        options.scales.y.title.text = `${yInfo.label} (${yInfo.unit})`;
        options.scales.x.min = line.min;
        options.scales.x.max = line.max;

        const dataset = this.chart.data.datasets[0];
        dataset.data = this.generateChartData(line);
        dataset.label = yInfo.label;
        dataset.borderColor = yInfo.color;
        dataset.backgroundColor = yInfo.color.replace('0.7', '0.1');

        // 現在値のマーカー
        options.plugins.annotation.annotations = {
            currentValue: {
                type: 'line',
                scaleID: 'x',
                value: this.latest.values[this.selectedXParam],
                borderColor: 'rgba(255, 99, 132, 0.8)',
                borderWidth: 2,
                borderDash: [5, 5],
                label: {
                    display: true,
                    content: '現在値',
                    position: 'start',
                    backgroundColor: 'rgba(255, 99, 132, 0.8)',
                    font: { size: 12, weight: 'bold' }
                }
            }
        };
        this.chart.update();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (typeof Chart === 'undefined') {
        // Chart.js はアプリに同梱している(app/static/vendor/chartjs/)。インターネットからは読まない
        console.error('Chart.js library is not loaded.');
        return;
    }
    window.plateParameterChart = new PlateParameterChart();
});
