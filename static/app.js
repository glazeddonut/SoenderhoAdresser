// Default polygon for Sønderho village [lon, lat]
// Covers the Sønderho village and summer house area on southern Fanø
const DEFAULT_POLYGON = [
  [8.441, 55.341],
  [8.458, 55.385],
  [8.476, 55.381],
  [8.476, 55.340],
  [8.441, 55.340],
];

const TYPE_COLORS = {
  'helårshus': '#3b82f6',
  'fritidshus': '#f97316',
  'andet': '#9ca3af',
};

const TYPE_LABELS = {
  'helårshus': 'Helårshus',
  'fritidshus': 'Fritidshus',
  'andet': 'Andet',
};

let map, drawnItems, currentPolygonLayer, markerLayer;
let allResults = [];
let filteredResults = [];
let sortCol = null;
let sortAsc = true;

function initMap() {
  map = L.map('map').setView([55.360, 8.458], 13);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);

  markerLayer = L.featureGroup().addTo(map);

  const drawControl = new L.Control.Draw({
    draw: {
      polygon: {
        shapeOptions: { color: '#6366f1', fillOpacity: 0.08, weight: 2 },
        showArea: false,
      },
      polyline: false,
      rectangle: false,
      circle: false,
      circlemarker: false,
      marker: false,
    },
    edit: {
      featureGroup: drawnItems,
      remove: false,
    },
  });
  map.addControl(drawControl);

  map.on(L.Draw.Event.CREATED, (e) => {
    drawnItems.clearLayers();
    currentPolygonLayer = e.layer;
    drawnItems.addLayer(currentPolygonLayer);
  });

  map.on(L.Draw.Event.EDITED, () => {
    currentPolygonLayer = drawnItems.getLayers()[0] || null;
  });

  // Add legend
  const legend = L.control({ position: 'bottomleft' });
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'map-legend');
    div.innerHTML = Object.entries(TYPE_LABELS).map(([key, label]) =>
      `<div><span class="legend-dot" style="background:${TYPE_COLORS[key]}"></span>${label}</div>`
    ).join('');
    return div;
  };
  legend.addTo(map);

  // Default Sønderho polygon
  const latlngs = DEFAULT_POLYGON.map(([lon, lat]) => [lat, lon]);
  currentPolygonLayer = L.polygon(latlngs, {
    color: '#6366f1',
    fillOpacity: 0.08,
    weight: 2,
  });
  drawnItems.addLayer(currentPolygonLayer);
  map.fitBounds(currentPolygonLayer.getBounds(), { padding: [30, 30] });
}

function getPolygon() {
  if (!currentPolygonLayer) return null;
  const latlngs = currentPolygonLayer.getLatLngs()[0];
  return latlngs.map((ll) => [ll.lng, ll.lat]);
}

async function search() {
  const polygon = getPolygon();
  if (!polygon) {
    setStatus('Tegn en polygon på kortet først.', 'error');
    return;
  }

  setStatus('Henter adresser og bygningsdata… (første søgning kan tage 30-60 sek.)', 'loading');
  document.getElementById('search-btn').disabled = true;

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ polygon }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allResults = await res.json();
    setStatus('', '');
    applyFilters();
  } catch (e) {
    setStatus(`Fejl: ${e.message}`, 'error');
  } finally {
    document.getElementById('search-btn').disabled = false;
  }
}

function applyFilters() {
  const type = document.getElementById('filter-type').value;
  const minBoli = parseFloat(document.getElementById('filter-min').value) || 0;
  const maxBoli = parseFloat(document.getElementById('filter-max').value) || Infinity;
  const minBeb = parseFloat(document.getElementById('filter-beb-min').value) || 0;
  const maxBeb = parseFloat(document.getElementById('filter-beb-max').value) || Infinity;
  const minAar = parseInt(document.getElementById('filter-aar-min').value) || 0;
  const maxAar = parseInt(document.getElementById('filter-aar-max').value) || 9999;

  const fredningFilter = document.getElementById('filter-fredet').value;

  filteredResults = allResults.filter((r) => {
    if (type !== 'alle' && r.type !== type) return false;

    const boli = r.boligareal ?? 0;
    if (boli < minBoli || boli > maxBoli) return false;

    const beb = r.bebygget_areal ?? 0;
    if (beb < minBeb || beb > maxBeb) return false;

    if (r.opfoerelse_aar != null) {
      if (r.opfoerelse_aar < minAar || r.opfoerelse_aar > maxAar) return false;
    } else if (minAar > 0 || maxAar < 9999) {
      return false;
    }

    if (fredningFilter === 'kun' && !r.fredet) return false;
    if (fredningFilter === 'ikke' && r.fredet) return false;

    return true;
  });

  if (sortCol) applySort();
  updateMap();
  updateTable();
}

function sortBy(col) {
  if (sortCol === col) {
    sortAsc = !sortAsc;
  } else {
    sortCol = col;
    sortAsc = true;
  }
  applySort();
  updateTable();
}

function applySort() {
  filteredResults.sort((a, b) => {
    let av = a[sortCol];
    let bv = b[sortCol];
    if (av == null) av = sortAsc ? Infinity : -Infinity;
    if (bv == null) bv = sortAsc ? Infinity : -Infinity;
    if (typeof av === 'boolean') return sortAsc ? (av ? -1 : 1) : (av ? 1 : -1);
    if (typeof av === 'string') return sortAsc ? av.localeCompare(bv, 'da') : bv.localeCompare(av, 'da');
    return sortAsc ? av - bv : bv - av;
  });
}

function updateMap() {
  markerLayer.clearLayers();

  filteredResults.forEach((r) => {
    if (r.x == null || r.y == null) return;

    const color = TYPE_COLORS[r.type] || TYPE_COLORS.andet;
    const marker = L.circleMarker([r.y, r.x], {
      radius: 6,
      fillColor: color,
      color: '#fff',
      weight: 1.5,
      fillOpacity: 0.85,
    });

    marker.bindPopup(`
      <div class="popup-inner">
        <strong>${r.adresse}</strong>
        <span class="popup-badge" style="background:${color}">${TYPE_LABELS[r.type] || r.type}</span>
        ${r.fredet ? '<span class="popup-badge popup-badge-fredet">Fredet</span>' : ''}
        ${r.boligareal != null ? `<div>Boligareal: <b>${r.boligareal} m²</b></div>` : ''}
        ${r.bebygget_areal != null ? `<div>Bebygget areal: <b>${r.bebygget_areal} m²</b></div>` : ''}
        ${r.opfoerelse_aar ? `<div>Opført: <b>${r.opfoerelse_aar}</b></div>` : ''}
      </div>
    `);

    marker._resultId = r.id;
    markerLayer.addLayer(marker);
  });

  const total = allResults.length;
  const shown = filteredResults.length;
  const countEl = document.getElementById('results-count');
  if (total === 0) {
    countEl.textContent = '';
  } else if (shown === total) {
    countEl.textContent = `${total} adresse${total !== 1 ? 'r' : ''}`;
  } else {
    countEl.textContent = `${shown} ud af ${total} adresser`;
  }
}

function updateTable() {
  const tbody = document.getElementById('results-body');
  const empty = document.getElementById('empty-state');
  const table = document.getElementById('results-table');

  if (allResults.length === 0) {
    empty.textContent = 'Søg for at se adresser';
    empty.style.display = 'flex';
    table.style.display = 'none';
    return;
  }

  if (filteredResults.length === 0) {
    empty.textContent = 'Ingen adresser matcher filteret';
    empty.style.display = 'flex';
    table.style.display = 'none';
    return;
  }

  empty.style.display = 'none';
  table.style.display = 'table';

  // Update sort icons in headers
  document.querySelectorAll('th[data-col]').forEach((th) => {
    const col = th.dataset.col;
    const icon = th.querySelector('.sort-icon');
    if (!icon) return;
    icon.textContent = col === sortCol ? (sortAsc ? ' ↑' : ' ↓') : '';
  });

  tbody.innerHTML = filteredResults.map((r) => {
    const color = TYPE_COLORS[r.type] || TYPE_COLORS.andet;
    return `
      <tr onclick="zoomTo('${r.id}')" data-id="${r.id}">
        <td class="td-address">${r.adresse}</td>
        <td><span class="type-dot" style="background:${color}"></span>${TYPE_LABELS[r.type] || r.type}</td>
        <td>${r.boligareal != null ? r.boligareal + ' m²' : '—'}</td>
        <td>${r.bebygget_areal != null ? r.bebygget_areal + ' m²' : '—'}</td>
        <td>${r.opfoerelse_aar ?? '—'}</td>
        <td>${r.fredet ? '<span class="fredet-badge">Ja</span>' : '—'}</td>
      </tr>
    `;
  }).join('');
}

function zoomTo(id) {
  markerLayer.eachLayer((marker) => {
    if (marker._resultId !== id) return;
    map.setView(marker.getLatLng(), 17);
    marker.openPopup();
  });

  document.querySelectorAll('#results-body tr').forEach((tr) => {
    tr.classList.toggle('active', tr.dataset.id === id);
  });

  // Scroll row into view
  const row = document.querySelector(`#results-body tr[data-id="${id}"]`);
  if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function setStatus(msg, type) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = type || '';
}

async function checkConfig() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    if (!cfg.bbr_enabled) {
      const hint = document.querySelector('.hint');
      if (hint) {
        hint.innerHTML = `
          <strong style="color:#f97316">BBR-data er ikke konfigureret.</strong>
          Opret service-bruger på
          <a href="https://datafordeler.dk" target="_blank">datafordeler.dk</a>
          og tilføj credentials til en <code>.env</code>-fil
          (se <code>.env.example</code>).
          Adresser vises uden bygningstype og areal.
        `;
      }
    }
  } catch (_) {}
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  checkConfig();
  search();
});
