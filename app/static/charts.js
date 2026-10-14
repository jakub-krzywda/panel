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

  function habitValue(data, raw) {
    return raw === null ? "nie śledzony" : `${raw}%`;
  }

  // Podpisy osi X; w widoku dziennym „pn 12.10" → dwie linie (dzień tygodnia nad datą).
  function axisLabels(data) {
    return (data.ticks ?? data.labels).map((t) => (t.includes(" ") ? t.split(" ") : t));
  }

  function habit(canvas, data, name, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: axisLabels(data), datasets: [bar("% wykonania", data.series[name], t.series1, t)] },
      options: {
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { title: title(data), label: (c) => habitValue(data, c.raw) } } },
        scales: { x: xAxis(t, { showTicks: data.ticks.length <= 8 }),
                  y: { min: 0, max: 100, ticks: { stepSize: 50, callback: (v) => `${v}%` } } },
      },
    });
  }

  function pomodoro(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: axisLabels(data), datasets: [bar("Pomodoro", data.pomodoro, t.series1, t)] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: title(data) } } },
                 scales: { x: xAxis(t), y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });
  }

  function walks(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "bar",
      data: { labels: axisLabels(data), datasets: [
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
      data: { labels: axisLabels(data), datasets: [
        line("SYS rano", data.morning_sys, t.series1, false),
        line("DIA rano", data.morning_dia, t.series2, false),
        line("SYS wieczorem", data.evening_sys, t.series1, true),
        line("DIA wieczorem", data.evening_dia, t.series2, true),
      ] },
      options: {
        plugins: { legend: { position: "top", align: "start", labels: { boxWidth: 24, boxHeight: 2 } },
                   tooltip: { callbacks: { title: title(data) } } },
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
      data: { labels: axisLabels(data), datasets: names.map((name) => {
        const slot = slots[name] ?? 0;
        return {
          label: labels[name] ?? name, data: data.series[name] ?? [], borderColor: t.series[slot], backgroundColor: t.series[slot],
          borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointStyle: POINT_STYLES[slot], spanGaps: false, tension: 0.2,
        };
      }) },
      options: {
        plugins: { legend: { position: "top", align: "start", labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
                   tooltip: { callbacks: { title: title(data), label: (c) => `${c.dataset.label}: ${c.raw === null ? "–" : habitValue(data, c.raw)}` } } },
        scales: { x: xAxis(t), y: { min: 0, max: 100, ticks: { stepSize: 25, callback: (v) => `${v}%` } } },
      },
    });
  }

  // Tydzień: punkt na każdy dzień = ile nawyków z `names` odhaczono (jak „SUMA DNIA"), plus średnia 7 dni.
  // `daily` to dane nawyków z osi dni; oś X podpisana numerem tygodnia na poniedziałkach.
  function checkedLine(canvas, daily, names, root) {
    const t = theme(root); base(t);
    const n = daily.dates.length;
    const perDay = daily.dates.map((_, i) => {
      const vals = names.map((h) => daily.counts[h]?.[i]).filter((v) => v !== null && v !== undefined);
      return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
    });
    const tracked = Math.max(1, ...daily.dates.map((_, i) =>
      names.filter((h) => (daily.counts[h]?.[i] ?? null) !== null).length));
    const avg7 = perDay.map((_, i) => {
      const win = perDay.slice(Math.max(0, i - 6), i + 1).filter((v) => v !== null);
      return win.length ? Math.round(10 * win.reduce((a, b) => a + b, 0) / win.length) / 10 : null;
    });
    const monday = (i) => daily.labels[i].startsWith("pn ");
    const step = Math.max(1, Math.ceil(n / 7 / 26));  // przy długiej historii co któryś tydzień, żeby się nie nakładały
    let weekIdx = -1;
    const tickText = daily.dates.map((_, i) => (monday(i) && ++weekIdx % step === 0) || i === 0 ? daily.weeks[i] : "");
    draw(canvas, {
      type: "line",
      data: { labels: tickText, datasets: [
        { label: "Odhaczone w dniu", data: perDay, borderColor: t.series1, backgroundColor: t.series1,
          borderWidth: 1, pointRadius: 2, pointHoverRadius: 5, spanGaps: false, tension: 0 },
        { label: "Średnia 7 dni", data: avg7, borderColor: t.series2, backgroundColor: t.series2,
          borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 4, spanGaps: true, tension: 0.3 },
      ] },
      options: {
        plugins: {
          legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 2 } },
          tooltip: { callbacks: {
            title: (items) => `${daily.labels[items[0].dataIndex]} · ${daily.weeks[items[0].dataIndex]}`,
            label: (c) => `${c.dataset.label}: ${c.raw === null ? "brak wpisu" : c.raw}`,
          } },
        },
        scales: {
          x: { grid: { color: (c) => (c.index !== undefined && monday(c.index) ? t.grid : "transparent"), drawTicks: false },
               border: { display: false },
               ticks: { autoSkip: false, maxRotation: 0, font: { size: 10 }, padding: 4 } },
          y: { beginAtZero: true, suggestedMax: tracked, ticks: { precision: 0 },
               title: { display: true, text: "nawyki / dzień" } },
        },
      },
    });
  }

  // Dzień: siatka nawyki × dni jak kratki w notesie. Odhaczone = kolor nawyku; nieodhaczone i nieśledzone
  // wyglądają tak samo (pusta kratka). Wiersze tylko dla nawyków, które mają jakikolwiek wpis w oknie,
  // chyba że `always` — wtedy zawsze (wybór użytkownika w widżecie).
  function habitGrid(el, data, names, slots, labels, { always = false } = {}) {
    const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
    const rows = names.filter((h) => always || (data.series[h] ?? []).some((v) => v !== null));
    const color = (h) => (h in slots ? `var(--series-${slots[h] + 1})` : "var(--axis)");
    const head = data.dates.map((iso, i) => {
      const [wd, dm] = data.ticks[i].split(" ");
      return `<th scope="col"><a href="/day/${iso}">${esc(wd)}<br>${esc(dm)}</a></th>`;
    }).join("");
    const body = rows.map((h) => `<tr><th scope="row">${esc(labels[h] ?? h)}</th>${data.dates.map((_, i) => {
      const v = data.series[h]?.[i];
      const on = v !== null && v !== undefined && v > 0;
      const state = on ? "✓" : v === null || v === undefined ? "brak wpisu" : "✗";
      return `<td><span class="hg${on ? " on" : ""}" style="--c: ${color(h)}" title="${esc(labels[h] ?? h)} · ${esc(data.labels[i])}: ${state}"></span></td>`;
    }).join("")}</tr>`).join("");
    const sums = data.dates.map((_, i) => {
      const vals = rows.map((h) => data.series[h]?.[i]).filter((v) => v !== null && v !== undefined);
      return `<td>${vals.length ? vals.filter((v) => v > 0).length : ""}</td>`;
    }).join("");
    el.innerHTML = rows.length
      ? `<table class="habit-grid"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody>
         <tfoot><tr><th scope="row">Suma</th>${sums}</tr></tfoot></table>`
      : `<p class="muted">Brak nawyków w tym oknie.</p>`;
  }

  function temperature(canvas, data, root) {
    const t = theme(root); base(t);
    draw(canvas, {
      type: "line",
      data: { labels: axisLabels(data), datasets: [{
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
      data: { labels: axisLabels(data), datasets: [bar("Opady (mm)", data.precip, t.series1, t)] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: title(data), label: (c) => `${c.raw} mm` } } },
                 scales: { x: xAxis(t), y: { beginAtZero: true, title: { display: true, text: "mm" } } } },
    });
  }

  // Okno widoku dziennego: wycina [from, to) ze wszystkich szeregów leżących na osi dni.
  // Pomijamy listy nazw nawyków (current/legacy), które też są tablicami, ale nie szeregami.
  const NOT_SERIES = new Set(["current", "legacy"]);
  function slice(data, from, to) {
    const cut = (v) => v.slice(from, to);
    return Object.fromEntries(Object.entries(data).map(([k, v]) => {
      if (k === "series" || k === "counts") return [k, Object.fromEntries(Object.entries(v).map(([h, s]) => [h, cut(s)]))];
      return [k, Array.isArray(v) && !NOT_SERIES.has(k) ? cut(v) : v];
    }));
  }

  // Przesuwane okno `size` dni na osi `dates` (ISO, ciągłe). Każdy dzień może być pierwszym w oknie.
  // `start` — data początku (null = ostatnie dni). onChange(index, isoStart, followsLatest).
  function timeline(el, dates, size, start, onChange) {
    const range = el.querySelector("input[type=range]");
    const picker = el.querySelector("input[type=date]");
    const out = el.querySelector("[data-range]");
    const max = Math.max(0, dates.length - size);
    const fmt = (iso) => iso.split("-").reverse().join(".");
    range.max = max;
    if (dates.length) { picker.min = dates[0]; picker.max = dates[max]; }
    const indexOf = (iso) => { const i = dates.findIndex((d) => d >= iso); return i === -1 ? max : i; };
    let i = start ? indexOf(start) : max;

    function set(n, notify = true) {
      i = Math.min(max, Math.max(0, n));
      range.value = i;
      picker.value = dates[i] ?? "";
      const last = dates[Math.min(dates.length, i + size) - 1];
      out.textContent = dates.length ? `${fmt(dates[i])} – ${fmt(last)}` : "brak danych";
      el.querySelectorAll("[data-step]").forEach((b) => {
        b.disabled = +b.dataset.step < 0 ? i === 0 : i === max;
      });
      if (notify) onChange(i, dates[i], i === max);
    }

    el.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => set(i + +b.dataset.step)));
    range.addEventListener("input", () => set(+range.value));
    picker.addEventListener("change", () => picker.value && set(indexOf(picker.value)));
    set(i, false);
    return { get index() { return i; } };
  }

  return { habit, habitLines, habitGrid, checkedLine, pomodoro, walks, bloodPressure, temperature, precipitation,
           slice, timeline };
})();
