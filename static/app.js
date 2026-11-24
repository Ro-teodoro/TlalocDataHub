let allStations = [];
let visibleStations = [];
let selectedClave = null;

const map = L.map("map", { preferCanvas: true }).setView([23.5, -102], 5);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; OpenStreetMap',
  maxZoom: 19,
}).addTo(map);

const markers = L.markerClusterGroup({
  disableClusteringAtZoom: 10,
  maxClusterRadius: 45,
});
map.addLayer(markers);

const searchInput = document.getElementById("search-input");
const stateFilter = document.getElementById("state-filter");
const situationFilter = document.getElementById("situation-filter");

function situationClass(situation) {
  return situation === "OPERANDO" ? "operando" : "suspendida";
}

function renderMarkers(stations) {
  markers.clearLayers();
  const items = [];
  for (const station of stations) {
    const icon = L.divIcon({
      className: "station-marker",
      html: `<span class="${situationClass(station.situacion)}"></span>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
    const marker = L.marker([station.lat, station.lon], { icon });
    marker.bindPopup(`
      <div class="popup-title">${escapeHtml(station.nombre)}</div>
      <div class="popup-meta">Clave ${escapeHtml(station.clave)} · ${escapeHtml(station.estado)}</div>
      <button class="popup-button" data-clave="${escapeHtml(station.clave)}">Ver datos</button>
    `);
    marker.on("popupopen", (event) => {
      event.popup.getElement()?.querySelector(".popup-button")?.addEventListener("click", () => {
        selectStation(station.clave);
      });
    });
    items.push(marker);
  }
  markers.addLayers(items);
  document.getElementById("station-count").textContent =
    `${stations.length.toLocaleString("es-MX")} estaciones visibles`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

async function loadStations() {
  const response = await fetch("/api/stations");
  allStations = await response.json();
  visibleStations = allStations;

  const states = [...new Set(allStations.map(station => station.estado).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "es"));
  for (const state of states) {
    const option = document.createElement("option");
    option.value = state;
    option.textContent = state;
    stateFilter.appendChild(option);
  }
  applyFilters();
}

function applyFilters() {
  const q = searchInput.value.trim().toLowerCase();
  const state = stateFilter.value.toLowerCase();
  const situation = situationFilter.value.toLowerCase();
  visibleStations = allStations.filter(station =>
    (!q || `${station.clave} ${station.nombre} ${station.municipio}`.toLowerCase().includes(q))
    && (!state || station.estado.toLowerCase() === state)
    && (!situation || station.situacion.toLowerCase() === situation)
  );
  renderMarkers(visibleStations);
}

async function selectStation(clave) {
  selectedClave = clave;
  const station = allStations.find(item => item.clave === clave);
  if (!station) return;

  document.getElementById("download-modal").classList.add("hidden");
  document.getElementById("station-detail").classList.remove("hidden");
  document.getElementById("detail-key").textContent = `CLAVE ${station.clave}`;
  document.getElementById("detail-name").textContent = station.nombre;
  document.getElementById("detail-meta").innerHTML = `
    ${metaItem("Estado", station.estado)}
    ${metaItem("Municipio", station.municipio)}
    ${metaItem("Situación", station.situacion)}
    ${metaItem("Altitud", `${station.altitud} msnm`)}
  `;
  document.getElementById("preview-body").innerHTML =
    `<tr><td colspan="5">Cargando registros…</td></tr>`;

  try {
    const response = await fetch(`/api/stations/${encodeURIComponent(clave)}/preview`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Error al cargar datos");
    document.getElementById("record-count").textContent = `${data.count} registros`;
    renderStatistics(data.statistics);
    document.getElementById("preview-body").innerHTML = data.rows.map(row => `
      <tr>
        <td>${escapeHtml(row.fecha)}</td>
        <td>${escapeHtml(row.precip)}</td>
        <td>${escapeHtml(row.evap)}</td>
        <td>${escapeHtml(row.tmax)}</td>
        <td>${escapeHtml(row.tmin)}</td>
      </tr>
    `).join("");
  } catch (error) {
    document.getElementById("preview-body").innerHTML =
      `<tr><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
  }
}

function metaItem(label, value) {
  return `<div class="meta-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "—")}</strong></div>`;
}

function formatStatistic(value, unit) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toLocaleString("es-MX", { maximumFractionDigits: 2 })} ${unit}`;
}

function renderStatistics(statistics) {
  if (!statistics) return;
  const period = statistics.periodo;
  document.getElementById("statistics-period").textContent =
    period.inicio && period.fin ? `${period.inicio} a ${period.fin}` : "";

  const cards = [
    ["Rango de fechas", [
      ["Inicio", period.inicio || "—"],
      ["Fin", period.fin || "—"],
      ["Días calendario", formatStatistic(period.dias, "días")],
      ["Registros", formatStatistic(statistics.periodo.registros, "filas")],
    ]],
    ["Precipitación", [
      ["Registros válidos", formatStatistic(statistics.precip.observaciones, "filas")],
      ["Total", formatStatistic(statistics.precip.total, "mm")],
      ["Promedio", formatStatistic(statistics.precip.promedio, "mm/día")],
      ["Máximo", formatStatistic(statistics.precip.maximo, "mm")],
      ["Nulos", formatStatistic(statistics.precip.nulos, "registros")],
      ["Porcentaje nulo", formatStatistic(statistics.precip.porcentaje_nulos, "%")],
    ]],
    ["Evaporación", [
      ["Registros válidos", formatStatistic(statistics.evap.observaciones, "filas")],
      ["Total", formatStatistic(statistics.evap.total, "mm")],
      ["Promedio", formatStatistic(statistics.evap.promedio, "mm/día")],
      ["Máximo", formatStatistic(statistics.evap.maximo, "mm")],
      ["Nulos", formatStatistic(statistics.evap.nulos, "registros")],
      ["Porcentaje nulo", formatStatistic(statistics.evap.porcentaje_nulos, "%")],
    ]],
    ["Temperatura máxima", [
      ["Registros válidos", formatStatistic(statistics.tmax.observaciones, "filas")],
      ["Promedio", formatStatistic(statistics.tmax.promedio, "°C")],
      ["Máxima", formatStatistic(statistics.tmax.maximo, "°C")],
      ["Nulos", formatStatistic(statistics.tmax.nulos, "registros")],
      ["Porcentaje nulo", formatStatistic(statistics.tmax.porcentaje_nulos, "%")],
    ]],
    ["Temperatura mínima", [
      ["Registros válidos", formatStatistic(statistics.tmin.observaciones, "filas")],
      ["Promedio", formatStatistic(statistics.tmin.promedio, "°C")],
      ["Mínima", formatStatistic(statistics.tmin.minimo, "°C")],
      ["Nulos", formatStatistic(statistics.tmin.nulos, "registros")],
      ["Porcentaje nulo", formatStatistic(statistics.tmin.porcentaje_nulos, "%")],
    ]],
  ];

  document.getElementById("statistics-grid").innerHTML = cards.map(([title, values]) => `
    <article class="stat-card">
      <h4>${escapeHtml(title)}</h4>
      <dl>${values.map(([label, value]) =>
        `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`
      ).join("")}</dl>
    </article>
  `).join("");
}

searchInput.addEventListener("input", applyFilters);
stateFilter.addEventListener("change", applyFilters);
situationFilter.addEventListener("change", applyFilters);
document.getElementById("close-detail").addEventListener("click", () => {
  document.getElementById("station-detail").classList.add("hidden");
});
document.getElementById("download-button").addEventListener("click", () => {
  if (!selectedClave) return;
  const variable = document.getElementById("variable-select").value;
  const mode = document.getElementById("mode-select").value;
  const format = document.getElementById("format-select").value;
  const method = "auto";
  const params = new URLSearchParams({ variable, mode, format, method });
  openDownloadSummary(selectedClave, variable, mode, format, params);
});

async function openDownloadSummary(clave, variable, mode, format, params) {
  const modal = document.getElementById("download-modal");
  const summaryContainer = document.getElementById("download-summary");
  const methodSection = document.getElementById("modal-method-section");
  const methodSelect = document.getElementById("method-select");
  methodSelect.value = "auto";
  methodSection.classList.toggle("hidden", mode !== "complemented");
  modal.classList.remove("hidden");
  summaryContainer.textContent = "Calculando resumen y métricas…";
  document.getElementById("download-modal-title").textContent =
    `${variable === "precip" ? "Precipitación" : variable === "evap" ? "Evaporación" : variable === "tmax" ? "Temperatura máxima" : "Temperatura mínima"} · Clave ${clave}`;

  try {
    const method = methodSelect.value;
    const summaryParams = new URLSearchParams({ variable, mode, method });
    const response = await fetch(
      `/api/stations/${encodeURIComponent(clave)}/completion-summary?${summaryParams}`
    );
    const summary = await response.json();
    if (!response.ok) throw new Error(summary.error || "No se pudo generar el resumen");

    const items = [
      metaItem("Total de registros", summary.total_registros),
      metaItem("Observados", summary.observados),
      metaItem("Nulos", summary.nulos),
      metaItem("Porcentaje nulo", `${summary.porcentaje_nulos} %`),
      metaItem("Complementados", summary.complementados),
      metaItem("Sin completar", summary.sin_completar),
      metaItem("Método", summary.metodo),
      metaItem("Método sugerido", summary.metodo_sugerido || "N/D"),
      metaItem("Razón", summary.razon_sugerencia || "No aplica"),
    ];

    if (summary.precision) {
      const precision = summary.precision;
      items.push(
        metaItem("Validación", precision.prueba),
        metaItem("MAE", precision.mae === null ? "N/D" : String(precision.mae)),
        metaItem("RMSE", precision.rmse === null ? "N/D" : String(precision.rmse)),
        metaItem("Sesgo", precision.bias === null ? "N/D" : String(precision.bias)),
        metaItem("R²", precision.r2 === null ? "N/D" : String(precision.r2)),
        metaItem("Prueba", `${precision.observaciones} observaciones`)
      );
    }
    summaryContainer.innerHTML = items.join("");

    document.getElementById("method-recommendation").textContent =
      `Sugerido: ${summary.metodo_sugerido}. ${summary.razon_sugerencia}`;
    currentModalDownload = { clave, variable, mode, format, methodSelect };
    updateModalDownloadLinks();
  } catch (error) {
    summaryContainer.innerHTML =
      `<div class="meta-item"><span>Error</span><strong>${escapeHtml(error.message)}</strong></div>`;
  }
}

document.getElementById("close-download-modal").addEventListener("click", () => {
  document.getElementById("download-modal").classList.add("hidden");
});

let currentModalDownload = null;

function updateModalDownloadLinks() {
  if (!currentModalDownload) return;
  const { clave, variable, mode, format, methodSelect } = currentModalDownload;
  const method = methodSelect.value;
  const dataParams = new URLSearchParams({ variable, mode, format, method });
  const reportParams = new URLSearchParams({ variable, mode, method });
  document.getElementById("modal-download-data").onclick = () => {
    window.location.href =
      `/api/stations/${encodeURIComponent(clave)}/download-variable?${dataParams}`;
  };
  document.getElementById("modal-download-report").onclick = () => {
    window.location.href =
      `/api/stations/${encodeURIComponent(clave)}/download-completion-report?${reportParams}`;
  };
}

document.getElementById("method-select").addEventListener("change", async () => {
  if (!currentModalDownload) return;
  const { clave, variable, mode } = currentModalDownload;
  const method = document.getElementById("method-select").value;
  updateModalDownloadLinks();
  const summaryContainer = document.getElementById("download-summary");
  summaryContainer.textContent = "Calculando método seleccionado…";
  try {
    const params = new URLSearchParams({ variable, mode, method });
    const response = await fetch(
      `/api/stations/${encodeURIComponent(clave)}/completion-summary?${params}`
    );
    const summary = await response.json();
    if (!response.ok) throw new Error(summary.error || "No se pudo calcular el resumen");

    const items = [
      metaItem("Total de registros", summary.total_registros),
      metaItem("Observados", summary.observados),
      metaItem("Nulos", summary.nulos),
      metaItem("Porcentaje nulo", `${summary.porcentaje_nulos} %`),
      metaItem("Complementados", summary.complementados),
      metaItem("Sin completar", summary.sin_completar),
      metaItem("Método", summary.metodo),
      metaItem("Método sugerido", summary.metodo_sugerido || "N/D"),
      metaItem("Razón", summary.razon_sugerencia || "No aplica"),
    ];
    if (summary.precision) {
      const precision = summary.precision;
      items.push(
        metaItem("MAE", precision.mae === null ? "N/D" : String(precision.mae)),
        metaItem("RMSE", precision.rmse === null ? "N/D" : String(precision.rmse)),
        metaItem("Sesgo", precision.bias === null ? "N/D" : String(precision.bias)),
        metaItem("R²", precision.r2 === null ? "N/D" : String(precision.r2))
      );
    }
    summaryContainer.innerHTML = items.join("");
    document.getElementById("method-recommendation").textContent =
      `Sugerido: ${summary.metodo_sugerido}. ${summary.razon_sugerencia}`;
  } catch (error) {
    summaryContainer.innerHTML =
      `<div class="meta-item"><span>Error</span><strong>${escapeHtml(error.message)}</strong></div>`;
  }
});

loadStations();
