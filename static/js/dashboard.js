/* Charts of the authority dashboard (Chart.js).
 * The aggregates are rendered into the page as JSON by the view, so the charts
 * need no extra request; the refresh button re-reads /authority/api/charts/. */
(function () {
  "use strict";

  var node = document.getElementById("charts-data");
  if (!node || typeof Chart === "undefined") { return; }

  var COLOURS = {
    critical: "#b3261e", high: "#c25e00", medium: "#1a73e8", low: "#5f6368",
    palette: ["#12395f", "#1a73e8", "#c25e00", "#1e7e34", "#6f2da8", "#b3261e",
              "#0f9b8e", "#8a6100", "#5f6368", "#2b6cb0"]
  };

  var data = JSON.parse(node.textContent || "{}");
  var charts = {};

  function drawTrend(trend) {
    var element = document.getElementById("trendChart");
    if (!element) { return; }
    charts.trend = new Chart(element, {
      type: "line",
      data: {
        labels: trend.map(function (row) { return row.date.slice(5); }),
        datasets: [{
          label: "Complaints received",
          data: trend.map(function (row) { return row.count; }),
          borderColor: COLOURS.palette[1],
          backgroundColor: "rgba(26,115,232,.12)",
          fill: true, tension: .3, pointRadius: 2
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }

  function drawStatus(rows) {
    var element = document.getElementById("statusChart");
    if (!element) { return; }
    charts.status = new Chart(element, {
      type: "doughnut",
      data: {
        labels: rows.map(function (row) { return row.status; }),
        datasets: [{
          data: rows.map(function (row) { return row.count; }),
          backgroundColor: COLOURS.palette
        }]
      },
      options: { plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } } }
    });
  }

  function drawCategory(rows) {
    var element = document.getElementById("categoryChart");
    if (!element) { return; }
    charts.category = new Chart(element, {
      type: "bar",
      data: {
        labels: rows.map(function (row) { return row.category__name; }),
        datasets: [{
          label: "Complaints",
          data: rows.map(function (row) { return row.count; }),
          backgroundColor: COLOURS.palette[0]
        }]
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }

  function drawPriority(rows) {
    var element = document.getElementById("priorityChart");
    if (!element) { return; }
    var order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
    var counts = order.map(function (name) {
      var found = rows.filter(function (row) { return row.priority === name; })[0];
      return found ? found.count : 0;
    });
    charts.priority = new Chart(element, {
      type: "bar",
      data: {
        labels: order,
        datasets: [{
          label: "Complaints",
          data: counts,
          backgroundColor: [COLOURS.critical, COLOURS.high, COLOURS.medium, COLOURS.low]
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }

  drawTrend(data.trend || []);
  drawStatus(data.by_status || []);
  drawCategory(data.by_category || []);
  drawPriority(data.by_priority || []);
})();
