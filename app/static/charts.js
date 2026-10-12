// Wykresy dziennika (Chart.js). Kolory z CSS (.viz), więc jasny/ciemny motyw działa bez zmian w JS.
window.DziennikCharts = (() => {
  const charts = new Map(); // canvas → Chart, żeby można było przerysować przy zmianie okresu

  function theme(root) {
    const css = getComputedStyle(root);
    const v = (name) => css.getPropertyValue(name).trim();
    return {
      series1: v("--series-1"), series2: v("--series-2"), grid: v("--grid"), axis: v("--axis"),
      surface: getComputedStyle(document.body).backgroundColor,
    };
  }

  function bar(label, data, color, t) {
    return {
      label, data, backgroundColor: color, borderColor: t.surface, borderWidth: 1,
      borderRadius: 4, borderSkipped: "bottom", maxBarThickness: 28,
      barPercentage: 0.7, categoryPercentage: 0.85,
    };
  }

  // Oś X: pionowa linia między okresami (offset), każdy okres podpisany, pełny zakres w tooltipie.
  function xAxis(t, { showTicks = true, stacked = false } = {}) {
    return {
      stacked,
      grid: { display: true, offset: true, color: t.grid, drawTicks: false },
      border: { display: false },
      ticks: { display: showTicks, autoSkip: false, maxRotation: 60, minRotation: 0, font: { size: 10 }, padding: 4 },
    };
  }

  function draw(canvas, config) {
    charts.get(canvas)?.destroy();
    charts.set(canvas, new Chart(canvas, config));
  }

  function base(t) {
    Chart.defaults.font.family = "system-ui, sans-serif";
    Chart.defaults.color = t.axis;
    Chart.defaults.borderColor = t.grid;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.tooltip.mode = "index";
    Chart.defaults.plugins.tooltip.intersect = false;
  }

  function title(data) {
    return (items) => data.labels[items[0].dataIndex];
  }

  function habit(canvas, data, name, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: data.ticks, datasets: [bar("% wykonania", data.series[name], t.series1, t)] },
      options: {
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { title: title(data), label: (c) => c.raw === null ? "nie śledzony" : `${c.raw}%` } } },
        scales: { x: xAxis(t, { showTicks: data.ticks.length <= 8 }),
                  y: { min: 0, max: 100, ticks: { stepSize: 50, callback: (v) => `${v}%` } } },
      },
    });
  }

  function pomodoro(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: data.ticks, datasets: [bar("Pomodoro", data.pomodoro, t.series1, t)] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: title(data) } } },
                 scales: { x: xAxis(t), y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });
  }

  function walks(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: data.ticks, datasets: [
        bar("13:00", data.walk_1300, t.series1, t),
        bar("20:00", data.walk_2000, t.series2, t),
      ] },
      options: {
        plugins: { legend: { position: "top", align: "start",
                             labels: { boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3 } },
                   tooltip: { callbacks: { title: title(data) } } },
        scales: { x: xAxis(t, { stacked: true }), y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
  }

  return { habit, pomodoro, walks };
})();
