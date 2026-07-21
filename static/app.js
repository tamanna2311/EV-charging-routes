(() => {
  "use strict";

  const form = document.querySelector("#trip-form");
  const results = document.querySelector("#results");
  const intro = document.querySelector("#intro");
  const errorBox = document.querySelector("#form-error");
  const planButton = document.querySelector("#plan-button");
  const panelScroll = document.querySelector("#panel-scroll");
  const mapStatus = document.querySelector("#map-status");
  const mapLegend = document.querySelector("#map-legend");
  const mapPickBanner = document.querySelector("#map-pick-banner");
  const mapPickText = document.querySelector("#map-pick-text");

  const state = {
    fields: {},
    picking: null,
    routePlans: [],
    selectedRouteIndex: 0,
    routeLines: [],
    markers: {},
    stationMarkers: [],
  };

  const map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([22.9, 79.2], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[character]);
  }

  function debounce(callback, delay) {
    let timer;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => callback(...args), delay);
    };
  }

  function apiError(data, fallback) {
    if (typeof data?.error === "string") return data.error;
    if (data?.error?.message) {
      const detail = data.error.details?.[0];
      return detail ? `${data.error.message} ${detail.field}: ${detail.message}` : data.error.message;
    }
    return fallback;
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    let data;
    try {
      data = await response.json();
    } catch (_error) {
      data = null;
    }
    if (!response.ok) throw new Error(apiError(data, "The service could not complete this request."));
    return data;
  }

  function createField(name) {
    const field = {
      name,
      input: document.querySelector(`#${name}-input`),
      status: document.querySelector(`#${name}-status`),
      suggestions: document.querySelector(`#${name}-suggestions`),
      selected: null,
      controller: null,
    };

    const updateSuggestions = debounce(async () => {
      const query = field.input.value.trim();
      if (query.length < 3 || field.selected?.label === query) {
        field.suggestions.innerHTML = "";
        return;
      }
      field.status.textContent = "Searching places…";
      field.status.className = "field-status";
      try {
        const data = await requestJson(`/api/v1/geocode?q=${encodeURIComponent(query)}`);
        renderSuggestions(field, data.results);
        field.status.textContent = data.results.length ? "Choose the closest match" : "No matching place found";
      } catch (error) {
        field.suggestions.innerHTML = "";
        field.status.textContent = error.message;
        field.status.className = "field-status error";
      }
    }, 650);

    field.input.addEventListener("input", () => {
      if (field.selected?.label !== field.input.value.trim()) field.selected = null;
      updateSuggestions();
    });
    field.input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") field.suggestions.innerHTML = "";
    });
    state.fields[name] = field;
    return field;
  }

  function renderSuggestions(field, choices) {
    field.suggestions.innerHTML = choices.map((choice, index) => `
      <button class="suggestion" type="button" role="option" data-index="${index}">
        <b>${escapeHtml(choice.label)}</b><small>${escapeHtml(choice.type || "place")}</small>
      </button>`).join("");
    field.suggestions.querySelectorAll(".suggestion").forEach((button) => {
      button.addEventListener("click", () => selectPlace(field, choices[Number(button.dataset.index)]));
    });
  }

  function selectPlace(field, place, updateMap = true) {
    field.selected = {
      label: place.label,
      latitude: Number(place.latitude),
      longitude: Number(place.longitude),
    };
    field.input.value = place.label;
    field.suggestions.innerHTML = "";
    field.status.textContent = "Place selected";
    field.status.className = "field-status";
    setPointMarker(field.name, field.selected);
    if (updateMap) map.flyTo([field.selected.latitude, field.selected.longitude], Math.max(map.getZoom(), 11), { duration: .6 });
  }

  function markerIcon(kind) {
    const label = kind === "origin" ? "A" : "B";
    return L.divIcon({
      className: "",
      html: `<div class="route-marker ${kind === "destination" ? "destination" : ""}">${label}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });
  }

  function setPointMarker(kind, point) {
    if (state.markers[kind]) state.markers[kind].remove();
    state.markers[kind] = L.marker([point.latitude, point.longitude], { icon: markerIcon(kind) })
      .bindTooltip(kind === "origin" ? "Start" : "Destination", { direction: "top", offset: [0, -10] })
      .addTo(map);
  }

  const originField = createField("origin");
  const destinationField = createField("destination");

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".place-control")) {
      originField.suggestions.innerHTML = "";
      destinationField.suggestions.innerHTML = "";
    }
  });

  async function resolvePlace(field) {
    const query = field.input.value.trim();
    if (!query) throw new Error(`Enter your ${field.name === "origin" ? "starting point" : "destination"}.`);
    if (field.selected && field.selected.label === query) return field.selected;
    field.status.textContent = "Finding this place…";
    const data = await requestJson(`/api/v1/geocode?q=${encodeURIComponent(query)}`);
    if (!data.results.length) throw new Error(`We could not find “${query}” in India. Try a more specific place name.`);
    selectPlace(field, data.results[0], false);
    return field.selected;
  }

  document.querySelectorAll(".map-pick").forEach((button) => {
    button.addEventListener("click", () => beginMapPick(button.dataset.target));
  });

  function beginMapPick(target) {
    state.picking = target;
    document.querySelectorAll(".map-pick").forEach((button) => button.classList.toggle("active", button.dataset.target === target));
    mapPickText.textContent = `Tap the map to choose your ${target === "origin" ? "starting point" : "destination"}`;
    mapPickBanner.hidden = false;
    map.getContainer().style.cursor = "crosshair";
  }

  function cancelMapPick() {
    state.picking = null;
    document.querySelectorAll(".map-pick").forEach((button) => button.classList.remove("active"));
    mapPickBanner.hidden = true;
    map.getContainer().style.cursor = "";
  }

  document.querySelector("#cancel-map-pick").addEventListener("click", cancelMapPick);
  map.on("click", (event) => {
    if (!state.picking) return;
    const field = state.fields[state.picking];
    const label = `Pinned location · ${event.latlng.lat.toFixed(5)}, ${event.latlng.lng.toFixed(5)}`;
    selectPlace(field, { label, latitude: event.latlng.lat, longitude: event.latlng.lng }, false);
    cancelMapPick();
  });

  document.querySelector("#use-location").addEventListener("click", () => {
    if (!navigator.geolocation) {
      originField.status.textContent = "Location access is not supported by this browser";
      originField.status.className = "field-status error";
      return;
    }
    originField.status.textContent = "Getting your location…";
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => selectPlace(originField, {
        label: `Current location · ${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}`,
        latitude: coords.latitude,
        longitude: coords.longitude,
      }),
      () => {
        originField.status.textContent = "Location permission was not available";
        originField.status.className = "field-status error";
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });

  document.querySelector("#swap-places").addEventListener("click", () => {
    const originValue = originField.input.value;
    const originSelected = originField.selected;
    originField.input.value = destinationField.input.value;
    originField.selected = destinationField.selected;
    destinationField.input.value = originValue;
    destinationField.selected = originSelected;
    if (originField.selected) setPointMarker("origin", originField.selected);
    if (destinationField.selected) setPointMarker("destination", destinationField.selected);
  });

  function numberValue(selector) {
    return Number(document.querySelector(selector).value);
  }

  function tripPayload(origin, destination) {
    return {
      origin,
      destination,
      vehicle: {
        battery_capacity_kwh: numberValue("#battery-capacity"),
        current_soc_percent: numberValue("#current-soc"),
        reserve_soc_percent: numberValue("#reserve-soc"),
        consumption_wh_per_km: numberValue("#consumption"),
        safety_buffer_percent: numberValue("#safety-buffer"),
        connector_types: Array.from(document.querySelectorAll('input[name="connector"]:checked')).map((input) => input.value),
        max_ac_kw: 7.2,
        max_dc_kw: 50,
      },
      preferences: {
        mode: document.querySelector('input[name="mode"]:checked').value,
        max_detour_km: numberValue("#max-detour"),
        minimum_station_confidence: 40,
        allow_unverified_connectors: document.querySelector("#allow-unverified").checked,
        maximum_results: 5,
      },
    };
  }

  function setLoading(loading) {
    planButton.disabled = loading;
    planButton.classList.toggle("loading", loading);
    planButton.querySelector("span").textContent = loading ? "Checking routes and stations" : "Plan my charging route";
    mapStatus.lastChild.textContent = loading ? " Planning your trip…" : " Ready for your route";
  }

  function clearMapPlan() {
    state.routeLines.forEach((line) => line.remove());
    state.stationMarkers.forEach((marker) => marker.remove());
    state.routeLines = [];
    state.stationMarkers = [];
  }

  function drawPlan(plan, selectedIndex) {
    clearMapPlan();
    const bounds = L.latLngBounds([]);
    state.routePlans.forEach((routePlan, index) => {
      const geometry = routePlan.route.geometry;
      if (!geometry?.length) return;
      const selected = index === selectedIndex;
      const line = L.polyline(geometry, {
        color: selected ? "#0b7a4b" : "#95a39c",
        weight: selected ? 6 : 3,
        opacity: selected ? .92 : .58,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(map);
      if (selected) line.bringToFront();
      state.routeLines.push(line);
      geometry.forEach((point) => bounds.extend(point));
    });

    setPointMarker("origin", plan.origin);
    setPointMarker("destination", plan.destination);
    bounds.extend([plan.origin.latitude, plan.origin.longitude]);
    bounds.extend([plan.destination.latitude, plan.destination.longitude]);

    plan.recommendations.forEach((station, index) => {
      const marker = L.marker([station.location.latitude, station.location.longitude], {
        icon: L.divIcon({
          className: "",
          html: `<div class="station-marker ${station.connector_verified ? "" : "unverified"}">${index + 1}</div>`,
          iconSize: [31, 31], iconAnchor: [15, 15],
        }),
      }).bindPopup(`<p class="popup-title">${escapeHtml(station.name)}</p><div class="popup-meta">Arrive near ${station.arrival_soc_percent}% · ${station.estimated_total_detour_km} km total detour</div>`).addTo(map);
      state.stationMarkers.push(marker);
      bounds.extend(marker.getLatLng());
    });
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [55, 55], maxZoom: 13 });
    window.setTimeout(() => map.invalidateSize(), 50);
  }

  function durationLabel(minutes) {
    if (!minutes) return "Time estimated";
    if (minutes < 60) return `${minutes} min`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  function renderRouteOptions() {
    const container = document.querySelector("#route-options");
    if (state.routePlans.length === 1) {
      const plan = state.routePlans[0];
      container.innerHTML = `<div class="one-route"><div><b>Best available road route</b><small>Charging stops are matched to this route</small></div><span>${plan.route.distance_km} km · ${escapeHtml(durationLabel(plan.route.duration_minutes))}</span></div>`;
      return;
    }
    container.innerHTML = `
      <div class="route-options-heading"><h3>Choose a road route</h3><span>Stops update for each route</span></div>
      <div class="route-list">${state.routePlans.map((plan, index) => {
        const stop = plan.decision.status === "no_stop_needed" ? "No charging stop needed" : plan.recommendations[0]?.name || "No reachable stop";
        return `<button class="route-option ${index === state.selectedRouteIndex ? "active" : ""}" type="button" data-index="${index}">
          <span><b>${escapeHtml(plan.route.label)}</b><small>${escapeHtml(stop)}</small></span>
          <span><b>${plan.route.distance_km} km</b><small>${escapeHtml(durationLabel(plan.route.duration_minutes))}</small></span>
        </button>`;
      }).join("")}</div>`;
    container.querySelectorAll(".route-option").forEach((button) => {
      button.addEventListener("click", () => renderPlan(state.routePlans[Number(button.dataset.index)], Number(button.dataset.index), true));
    });
  }

  function metric(value, label) {
    return `<div class="metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span></div>`;
  }

  function stationCard(station, index, chargingRequired) {
    const connectorText = station.connector_verified
      ? `Works with your ${station.matching_connectors.join(" / ")}`
      : "Connector details need confirmation";
    let advice;
    if (!chargingRequired) {
      advice = `Optional backup: you should reach this station with about <b>${station.arrival_soc_percent}%</b> battery.`;
    } else if (station.can_finish_after_charge) {
      const time = station.estimated_charge_minutes ? ` (roughly ${station.estimated_charge_minutes} min at the listed power)` : "";
      advice = `Arrive near <b>${station.arrival_soc_percent}%</b>, then charge to about <b>${station.suggested_target_soc_percent}%</b>${time}.`;
    } else {
      advice = "A single full charge here may not cover the remaining trip. Start with more charge or plan additional stops.";
    }
    const speed = station.power_kw ? `${station.power_kw} kW` : "Not listed";
    return `<article class="station-card ${index === 0 ? "best" : ""}" data-station-index="${index}">
      <div class="station-top">
        <div class="station-title"><span class="station-rank">${index + 1}</span><div><h4>${escapeHtml(station.name)}</h4><p>${escapeHtml(station.operator_name)}</p></div></div>
        ${index === 0 ? '<span class="best-label">Best fit</span>' : ""}
      </div>
      <span class="compatibility ${station.connector_verified ? "" : "unverified"}">${escapeHtml(connectorText)}</span>
      <div class="station-facts">
        <div><b>${station.distance_from_start_km} km</b><span>from start</span></div>
        <div><b>${station.estimated_total_detour_km} km</b><span>total detour</span></div>
        <div><b>${station.arrival_soc_percent}%</b><span>battery there</span></div>
        <div><b>${escapeHtml(speed)}</b><span>listed speed</span></div>
      </div>
      <div class="charge-advice">${advice}</div>
      <div class="reason-list">${station.reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div>
      <div class="station-actions"><span class="station-note">${escapeHtml(station.verification_note)}</span><a class="navigate-link" href="${escapeHtml(station.navigation_url)}" target="_blank" rel="noreferrer">Open directions <svg><use href="#icon-external"/></svg></a></div>
    </article>`;
  }

  function renderPlan(plan, selectedIndex = 0, keepOptions = false) {
    if (!keepOptions && Array.isArray(plan.route_options) && plan.route_options.length) {
      state.routePlans = plan.route_options;
      plan = state.routePlans[selectedIndex] || plan;
    }
    state.selectedRouteIndex = selectedIndex;
    drawPlan(plan, selectedIndex);
    form.hidden = true;
    intro.hidden = true;
    results.hidden = false;

    const icon = plan.decision.status === "no_stop_needed" ? "✓" : plan.decision.status === "stop_required" ? "⚡" : "!";
    document.querySelector("#decision-card").innerHTML = `<div class="decision-card ${plan.decision.status}"><div class="decision-top"><span class="decision-icon">${icon}</span><h3>${escapeHtml(plan.decision.title)}</h3></div><p>${escapeHtml(plan.decision.summary)}</p></div>`;
    renderRouteOptions();

    document.querySelector("#metrics").innerHTML = [
      metric(`${plan.route.distance_km} km`, "Road distance"),
      metric(durationLabel(plan.route.duration_minutes), "Drive time"),
      metric(`${plan.battery.estimated_direct_arrival_soc_percent}%`, "Arrival without charging"),
    ].join("");

    const chargingRequired = plan.decision.status !== "no_stop_needed";
    document.querySelector("#station-results").innerHTML = plan.recommendations.length
      ? `<div class="station-section-title"><h3>${chargingRequired ? "Best charging stops" : "Useful backup stations"}</h3><span>${plan.candidate_count} suitable records checked</span></div>${plan.recommendations.map((station, index) => stationCard(station, index, chargingRequired)).join("")}`
      : `<div class="empty-box"><b>No safe station match found on this route.</b><br>Try increasing your starting battery, allowing a longer detour or showing stations with incomplete connector data.</div>`;

    document.querySelector("#warnings").innerHTML = plan.warnings.length
      ? `<div class="warning-box">${plan.warnings.map((warning) => `• ${escapeHtml(warning)}`).join("<br>")}</div>` : "";
    document.querySelector("#calculation-content").innerHTML = `<ul>
      <li>The trip needs about ${plan.battery.energy_needed_kwh} kWh after the driving buffer.</li>
      <li>${plan.battery.safe_available_energy_kwh} kWh is available above your ${plan.battery.reserve_soc_percent}% reserve.</li>
      <li>Your safe range before reserve is about ${plan.battery.safe_range_km} km.</li>
      ${plan.assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>`;

    document.querySelectorAll(".station-card").forEach((card) => {
      card.addEventListener("mouseenter", () => {
        const marker = state.stationMarkers[Number(card.dataset.stationIndex)];
        if (marker) marker.openPopup();
      });
    });
    mapStatus.lastChild.textContent = plan.route.source === "osrm" ? " Route and charging stops ready" : " Estimated route ready";
    mapLegend.hidden = false;
    if (window.matchMedia("(max-width: 930px)").matches) results.scrollIntoView({ behavior: "smooth", block: "start" });
    else panelScroll.scrollTo({ top: 0, behavior: "smooth" });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.hidden = true;
    if (!form.reportValidity()) return;
    setLoading(true);
    try {
      const [origin, destination] = await Promise.all([resolvePlace(originField), resolvePlace(destinationField)]);
      const payload = tripPayload(origin, destination);
      if (!payload.vehicle.connector_types.length) throw new Error("Select at least one connector supported by your EV.");
      if (payload.vehicle.current_soc_percent < payload.vehicle.reserve_soc_percent) throw new Error("Your reserve cannot be higher than your current battery level.");
      const data = await requestJson("/api/v1/trips/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      renderPlan(data);
    } catch (error) {
      errorBox.textContent = error.message || "The trip could not be planned.";
      errorBox.hidden = false;
      errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
    } finally {
      setLoading(false);
    }
  });

  function editTrip() {
    results.hidden = true;
    form.hidden = false;
    intro.hidden = false;
    if (window.matchMedia("(max-width: 930px)").matches) intro.scrollIntoView({ behavior: "smooth", block: "start" });
    else panelScroll.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.querySelector("#edit-trip").addEventListener("click", editTrip);
  document.querySelector("#plan-another").addEventListener("click", editTrip);
  window.addEventListener("resize", () => map.invalidateSize());
})();

