// GRP map symbols, shared by every map page (docs/enhancement/GRP_Map_Icon_UX_Pack_v1.0, ADR-0062).
// Shape says what a point is, colour says where it comes from, and a separate ring and badge say
// its assessment status. Colour is never the only clue: every marker has its own glyph, a tooltip
// and an accessible name. Needs Leaflet; clustering uses leaflet.markercluster when it is loaded.
window.GRPMap = (() => {
  const ICON_BASE = "/assets/map-icons/";
  // Labels follow the owner's wording: "N/A" rather than "Unable to assess" (25 Sep 2026).
  const STATUS_SYMBOL = {
    potentially_exposed: { icon: "status-exposed.svg", css: "status-exposed", label: "Potentially exposed" },
    not_exposed_under_scenario: { icon: "status-not-exposed.svg", css: "status-not-exposed", label: "Not exposed under the selected scenario" },
    unable_to_assess: { icon: "status-unable.svg", css: "status-unable", label: "N/A — no data" },
  };
  // Live context classes, which are not assessment results.
  const STATES = {
    muted: "is-muted", near: "is-near-flood", review: "is-access-review", picture: "has-picture",
    offline: "is-offline", placeholder: "is-placeholder",
  };

  const iconImg = (file, className) => {
    const img = document.createElement("img");
    img.src = ICON_BASE + file;
    img.alt = "";
    img.className = className;
    img.draggable = false;
    return img;
  };

  // A pin with an optional status ring and badge, and optional live-context states.
  const pinIcon = (file, options = {}) => {
    const box = document.createElement("span");
    const statusSymbol = STATUS_SYMBOL[options.status];
    box.className = ["grp-pin", statusSymbol ? statusSymbol.css : "",
      ...Object.entries(STATES).filter(([key]) => options[key]).map(([, css]) => css)].filter(Boolean).join(" ");
    box.append(iconImg(file, "grp-pin__icon"));
    if (statusSymbol) box.append(iconImg(statusSymbol.icon, "grp-pin__badge"));
    return window.L.divIcon({
      html: box, className: "grp-map-marker", iconSize: [34, 40], iconAnchor: [17, 40],
      tooltipAnchor: [0, -38],
    });
  };

  const grpMarker = (latlng, file, options = {}) => {
    const marker = window.L.marker(latlng, {
      icon: pinIcon(file, options), keyboard: true, riseOnHover: true,
    });
    marker.grpSymbol = file;
    marker.grpKind = options.kind || "";
    // Keyboard and screen-reader users get the same information as the hover tooltip.
    marker.on("add", () => {
      const element = marker.getElement();
      if (!element) return;
      element.setAttribute("role", "button");
      if (options.label) element.setAttribute("aria-label", options.label);
    });
    return marker;
  };

  // A cluster shows its count and the dominant symbol (three quarters or more of its points); a
  // mixed cluster shows a neutral symbol.
  const DOMINANT_SHARE = 0.75;
  const clusterIcon = (cluster) => {
    const children = cluster.getAllChildMarkers();
    const tally = {};
    children.forEach((marker) => { tally[marker.grpSymbol] = (tally[marker.grpSymbol] || 0) + 1; });
    const [top, topCount] = Object.entries(tally).sort((a, b) => b[1] - a[1])[0] || [null, 0];
    const dominant = top && topCount / children.length >= DOMINANT_SHARE ? top : null;
    const box = document.createElement("span");
    box.className = `grp-cluster${dominant ? "" : " is-mixed"}`;
    box.setAttribute("role", "img");
    const names = [...new Set(children.map((m) => m.grpKind).filter(Boolean))].join(", ");
    box.setAttribute("aria-label", `${children.length} points${names ? `: ${names}` : ""}`);
    if (dominant) {
      box.append(iconImg(dominant, "grp-cluster__icon"));
    } else {
      const mixed = document.createElement("span");
      mixed.className = "grp-cluster__mixed";
      mixed.setAttribute("aria-hidden", "true");
      box.append(mixed);
    }
    const count = document.createElement("b");
    count.textContent = children.length.toLocaleString("en-GB");
    box.append(count);
    return window.L.divIcon({ html: box, className: "grp-map-marker grp-map-cluster", iconSize: [46, 46] });
  };

  // One cluster group per map. At high zoom points stand alone, and points on one spot spread
  // out (spiderfy) when clicked.
  const clusterGroup = () => (window.L.markerClusterGroup
    ? window.L.markerClusterGroup({
      maxClusterRadius: 48, disableClusteringAtZoom: 17, spiderfyOnMaxZoom: true,
      showCoverageOnHover: false, chunkedLoading: true, iconCreateFunction: clusterIcon,
    })
    : window.L.layerGroup());

  // A switch's points, shown through a shared cluster group. It answers the calls switch code
  // makes of a Leaflet layer: addTo, remove, eachLayer, and `shown`.
  const clusteredLayer = (group) => {
    const markers = [];
    return {
      markers,
      shown: false,
      addLayer(marker) { markers.push(marker); return this; },
      addTo(target) {
        if (!target.hasLayer(group)) group.addTo(target);
        if (group.addLayers) group.addLayers(markers);
        else markers.forEach((marker) => group.addLayer(marker));
        this.shown = true;
        return this;
      },
      remove() {
        if (group.removeLayers) group.removeLayers(markers);
        else markers.forEach((marker) => group.removeLayer(marker));
        this.shown = false;
        return this;
      },
      eachLayer(fn) { markers.forEach(fn); },
    };
  };

  // "You are here": the browser's position as a pulsing dot, with its accuracy as a light circle.
  const youAreHere = (lat, lon, accuracy, label = "You are here") => {
    const dot = document.createElement("span");
    dot.className = "grp-you";
    dot.setAttribute("role", "img");
    dot.setAttribute("aria-label", label);
    const group = window.L.featureGroup();
    if (accuracy && accuracy < 20000) {
      window.L.circle([lat, lon], {
        radius: accuracy, color: "#2563eb", weight: 1, opacity: 0.5, fillColor: "#2563eb",
        fillOpacity: 0.08, interactive: false,
      }).addTo(group);
    }
    window.L.marker([lat, lon], {
      icon: window.L.divIcon({ html: dot, className: "grp-map-marker grp-you-marker", iconSize: [22, 22], iconAnchor: [11, 11] }),
      keyboard: true, zIndexOffset: 1000, title: label,
    }).bindTooltip(label, { direction: "top", offset: [0, -10] }).addTo(group);
    return group;
  };

  // The same base map and attribution on every page. `credit` adds the page's data credits.
  const baseLayer = (credit = "") => window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: `&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors${credit ? ` · ${credit}` : ""}`,
  });

  // District and area outlines: the pack's navy, dashed; a selected area is solid and lightly filled.
  const BOUNDARY = "#28415E";
  const boundaryStyle = (selected = false) => ({
    color: BOUNDARY,
    weight: selected ? 3 : 2,
    dashArray: selected ? null : "6 5",
    fill: true,
    fillColor: BOUNDARY,
    fillOpacity: selected ? 0.08 : 0.03,
  });

  return {
    ICON_BASE, STATUS_SYMBOL, BOUNDARY, iconImg, pinIcon, grpMarker, clusterIcon, clusterGroup,
    clusteredLayer, youAreHere, baseLayer, boundaryStyle,
  };
})();
