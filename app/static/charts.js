// Wykresy dziennika (Chart.js). Kolory z CSS (.viz), więc jasny/ciemny motyw działa bez zmian w JS.
window.DziennikCharts = (() => {
  const charts = new Map(); // canvas → Chart, żeby można było przerysować przy zmianie okresu

  function theme(root) {
    const css = getComputedStyle(root);
    const v = (name) => css.getPropertyValue(name).trim();
    return {
      series: [1, 2, 3, 4, 5].map((i) => v(`--series-${i}`)),
      series1: v("--series-1"), series2: v("--series-2"), grid: v("--grid"), axis: v("--axis"),
      surface: v("--surface"),  // tło karty z wykresem — przerwy między słupkami w jego kolorze
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

  // Ciśnienie: SYS i DIA jedną skalą (ta sama jednostka); rano linia ciągła, wieczorem przerywana.
  function bloodPressure(canvas, data, root) {
    const t = theme(root); base(t);
    const line = (label, values, color, dashed) => ({
      label, data: values, borderColor: color, backgroundColor: color, borderWidth: 2,
      borderDash: dashed ? [6, 4] : [], pointRadius: 4, pointHoverRadius: 6, spanGaps: false,
    });
    draw(canvas, {
      type: "line",
      data: { labels: data.labels, datasets: [
        line("SYS rano", data.morning_sys, t.series1, false),
        line("DIA rano", data.morning_dia, t.series2, false),
        line("SYS wieczorem", data.evening_sys, t.series1, true),
        line("DIA wieczorem", data.evening_dia, t.series2, true),
      ] },
      options: {
        plugins: { legend: { position: "top", align: "start", labels: { boxWidth: 24, boxHeight: 2 } } },
        scales: { x: xAxis(t), y: { suggestedMin: 50, suggestedMax: 160, title: { display: true, text: "mmHg" } } },
      },
    });
  }

  // Kilka nawyków na jednym wykresie. Kolor i kształt punktu idą za nawykiem (slot = kolejność
  // z templatu), nie za kolejnością wyboru — wyłączenie jednego nie przemalowuje pozostałych.
  const POINT_STYLES = ["circle", "rect", "triangle", "rectRot", "star"];
  function habitLines(canvas, data, names, slots, labels, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "line",
      data: { labels: data.ticks, datasets: names.map((name) => {
        const slot = slots[name] ?? 0;
        return {
          label: labels[name] ?? name, data: data.series[name] ?? [], borderColor: t.series[slot], backgroundColor: t.series[slot],
          borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointStyle: POINT_STYLES[slot], spanGaps: false, tension: 0.2,
        };
      }) },
      options: {
        plugins: { legend: { position: "top", align: "start", labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
                   tooltip: { callbacks: { title: title(data), label: (c) => `${c.dataset.label}: ${c.raw === null ? "–" : c.raw + "%"}` } } },
        scales: { x: xAxis(t), y: { min: 0, max: 100, ticks: { stepSize: 25, callback: (v) => `${v}%` } } },
      },
    });
  }

  function temperature(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "line",
      data: { labels: data.ticks, datasets: [{
        label: "Śr. temperatura maks. (°C)", data: data.temp_max, borderColor: t.series2, backgroundColor: t.series2,
        borderWidth: 2, pointRadius: 3, spanGaps: false, tension: 0.2,
      }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: title(data), label: (c) => `${c.raw} °C` } } },
                 scales: { x: xAxis(t), y: { title: { display: true, text: "°C" } } } },
    });
  }

  function precipitation(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: data.ticks, datasets: [bar("Opady (mm)", data.precip, t.series1, t)] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: title(data), label: (c) => `${c.raw} mm` } } },
                 scales: { x: xAxis(t), y: { beginAtZero: true, title: { display: true, text: "mm" } } } },
    });
  }

  return { habit, habitLines, pomodoro, walks, bloodPressure, temperature, precipitation };
})();
