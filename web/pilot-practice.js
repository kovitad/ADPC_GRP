// Pilot Phase B1: a Thai riverside-village view of the synthetic HAND practice fixture.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const SVG = "http://www.w3.org/2000/svg";
  const PROFILE_ROW = 4;
  const HOUSES = {
    "4:7": { key: "A", label: "hd.house.a" },
    "4:18": { key: "B", label: "hd.house.b" },
  };
  const state = {
    data: null,
    asked: 0,
    timer: null,
    selected: { row: 4, col: 7 },
    showNumbers: false,
  };
  const say = PilotText.t;
  const metres = (value) => `${(Math.round(value * 10) / 10).toFixed(1)} m`;
  const cellKey = (row, col) => `${row}:${col}`;

  // Depth bands are presentation only. State, depth and counts all come from the server response.
  const band = (data, row, col) => {
    const kind = data.state[row][col];
    if (kind !== "wet") return kind;
    const depth = data.depth_m[row][col];
    if (depth <= 1) return "wet-1";
    if (depth <= 2) return "wet-2";
    return "wet-3";
  };

  const LEGEND = ["wet-1", "wet-2", "wet-3", "edge", "dry", "unknown", "outside"];

  const selectedName = (row, col) => {
    const house = HOUSES[cellKey(row, col)];
    return house ? say(house.label) : say("hd.cell.name", { row: row + 1, col: col + 1 });
  };

  const describe = (data, row, col) => {
    const hand = data.hand_m[row][col];
    const kind = data.state[row][col];
    if (kind === "outside") return say("hd.cell.outside");
    if (kind === "unknown") return say("hd.cell.unknown");
    const values = { h: metres(hand), w: metres(data.stage_m), d: metres(data.depth_m[row][col]) };
    if (kind === "wet") return say("hd.cell.wetSimple", values);
    if (kind === "edge") return say("hd.cell.edgeSimple", values);
    return say("hd.cell.drySimple", values);
  };

  const arithmetic = (data, row, col) => {
    const hand = data.hand_m[row][col];
    const kind = data.state[row][col];
    if (kind === "outside") return say("hd.arithmetic.outside");
    if (kind === "unknown") return say("hd.arithmetic.unknown");
    return say("hd.arithmetic.known", {
      w: metres(data.stage_m), h: metres(hand), d: metres(data.depth_m[row][col]),
    });
  };

  const renderSelectionText = (data) => {
    const { row, col } = state.selected;
    $("[data-hd-selected-title]").textContent = selectedName(row, col);
    $("[data-hd-cell]").textContent = describe(data, row, col);
    $("[data-hd-arithmetic]").textContent = arithmetic(data, row, col);
  };

  const renderLegend = (data) => {
    const counts = {};
    data.state.forEach((row, r) => row.forEach((_, c) => {
      const key = band(data, r, c);
      counts[key] = (counts[key] || 0) + 1;
    }));
    const list = $("[data-hd-legend]");
    list.replaceChildren();
    LEGEND.forEach((key) => {
      const li = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = `hd__swatch hd-c--${key}`;
      swatch.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.textContent = say(`hd.legend.${key}`);
      const count = document.createElement("span");
      count.className = "hd__count";
      count.textContent = String(counts[key] || 0);
      li.append(swatch, label, count);
      list.append(li);
    });
  };

  const selectCell = (row, col, { focus = false } = {}) => {
    state.selected = { row, col };
    if (!state.data) return;
    renderMap(state.data);
    renderSelectionText(state.data);
    renderProfile(state.data);
    if (focus) {
      const chosen = $("[data-hd-map]").querySelector(`[data-row="${row}"][data-col="${col}"]`);
      if (chosen) chosen.focus({ preventScroll: true });
    }
  };

  const moveSelection = (event, row, col) => {
    const moves = {
      ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0],
    };
    if (!moves[event.key] || !state.data) return;
    event.preventDefault();
    const [dr, dc] = moves[event.key];
    selectCell(
      Math.max(0, Math.min(state.data.rows - 1, row + dr)),
      Math.max(0, Math.min(state.data.cols - 1, col + dc)),
      { focus: true },
    );
  };

  const renderMap = (data) => {
    const map = $("[data-hd-map]");
    map.style.gridTemplateColumns = `repeat(${data.cols}, 1fr)`;
    map.setAttribute("aria-label", say("hd.map.aria"));
    map.replaceChildren();
    data.state.forEach((row, r) => row.forEach((_, c) => {
      const cell = document.createElement("button");
      const selected = r === state.selected.row && c === state.selected.col;
      const house = HOUSES[cellKey(r, c)];
      cell.type = "button";
      cell.role = "gridcell";
      cell.tabIndex = selected ? 0 : -1;
      cell.dataset.row = String(r);
      cell.dataset.col = String(c);
      cell.className = `hd__sq hd-c--${band(data, r, c)}`;
      if (c === data.channel_col && data.state[r][c] !== "outside") cell.classList.add("is-channel");
      if (house) cell.classList.add("is-house");
      if (selected) cell.classList.add("is-selected");
      cell.setAttribute("aria-selected", String(selected));
      const text = `${selectedName(r, c)}. ${describe(data, r, c)}`;
      cell.setAttribute("aria-label", text);
      cell.title = text;
      const hand = data.hand_m[r][c];
      if (state.showNumbers && hand !== null && data.state[r][c] !== "outside") {
        cell.textContent = hand.toFixed(1);
      }
      cell.addEventListener("click", () => selectCell(r, c));
      cell.addEventListener("keydown", (event) => moveSelection(event, r, c));
      map.append(cell);
    }));
  };

  const renderAnswer = (data) => {
    const n = data.counts;
    const known = n.wet + n.edge + n.dry;
    const water = metres(data.stage_m);
    const parts = [n.wet === 0
      ? say("hd.ans.none", { w: water })
      : say("hd.ans.some", { w: water, wet: n.wet, known })
        + (data.deep_cells ? say("hd.ans.deep", { deep: data.deep_cells }) : say("hd.ans.shallow"))];
    if (n.wet) parts.push(say("hd.ans.deepest", { d: metres(data.deepest_m) }));
    if (n.unknown) parts.push(say("hd.ans.unknown", { n: n.unknown }));
    $("[data-hd-answer]").textContent = parts.join(" ");
  };

  const el = (name, attrs = {}, text) => {
    const node = document.createElementNS(SVG, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // Illustration only: a Thai stilt house. It carries no floor height or indoor depth.
  const houseSymbol = (svg, x, groundY, scale) => {
    const g = el("g", { transform: `translate(${x} ${groundY}) scale(${scale})`, class: "hd-p--house-art" });
    g.append(el("path", { d: "M-40 0 v-18 M-14 0 v-18 M14 0 v-18 M40 0 v-18", class: "hd-p--stilt" }));
    g.append(el("rect", { x: -46, y: -56, width: 92, height: 40, class: "hd-p--wall" }));
    g.append(el("path", { d: "M-46 -44 h92 M-46 -32 h92", class: "hd-p--plank" }));
    g.append(el("rect", { x: -10, y: -50, width: 20, height: 34, class: "hd-p--door" }));
    g.append(el("rect", { x: -36, y: -48, width: 14, height: 14, class: "hd-p--window" }));
    g.append(el("rect", { x: 22, y: -48, width: 14, height: 14, class: "hd-p--window" }));
    g.append(el("path", { d: "M-58 -54 L-30 -94 L30 -94 L58 -54 Z", class: "hd-p--roof" }));
    g.append(el("path", { d: "M-30 -94 L-36 -106 M30 -94 L36 -106", class: "hd-p--finial" }));
    g.append(el("path", { d: "M-44 -66 h88 M-36 -80 h72", class: "hd-p--tile" }));
    svg.append(g);
  };

  // Drawn after the water and ground so the label and selection always stay readable.
  const houseLabel = (svg, x, groundY, label, selected, scale) => {
    if (selected) {
      svg.append(el("rect", {
        x: x - 62 * scale, y: groundY - 118 * scale, width: 124 * scale, height: 128 * scale, rx: 12, class: "hd-p--selected",
      }));
    }
    svg.append(el("text", { x, y: groundY - 124 * scale, class: "hd-p--house-label", "text-anchor": "middle" }, label));
  };

  const treeSymbol = (svg, x, groundY, scale) => {
    const g = el("g", { transform: `translate(${x} ${groundY}) scale(${scale})`, "aria-hidden": "true" });
    g.append(el("rect", { x: -4, y: -30, width: 8, height: 32, class: "hd-p--trunk" }));
    g.append(el("circle", { cx: 0, cy: -48, r: 26, class: "hd-p--leaf" }));
    g.append(el("circle", { cx: -15, cy: -36, r: 15, class: "hd-p--leaf-light" }));
    g.append(el("circle", { cx: 15, cy: -40, r: 16, class: "hd-p--leaf-dark" }));
    svg.append(g);
  };

  // Monotone cubic (Fritsch-Carlson) through the cell centres. It never overshoots the cell
  // values, so the drawn bank cannot dip below or rise above what the fixture says.
  const monotonePath = (pts) => {
    const k = pts.length;
    const d = [];
    const m = [];
    for (let i = 0; i < k - 1; i += 1) d.push((pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0]));
    m[0] = d[0];
    m[k - 1] = d[k - 2];
    for (let i = 1; i < k - 1; i += 1) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
    for (let i = 0; i < k - 1; i += 1) {
      if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      const a = m[i] / d[i];
      const b = m[i + 1] / d[i];
      const t = a * a + b * b;
      if (t > 9) { const q = 3 / Math.sqrt(t); m[i] = q * a * d[i]; m[i + 1] = q * b * d[i]; }
    }
    let out = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < k - 1; i += 1) {
      const h = pts[i + 1][0] - pts[i][0];
      out += ` C${(pts[i][0] + h / 3).toFixed(1)} ${(pts[i][1] + (m[i] * h) / 3).toFixed(1)}`
        + ` ${(pts[i + 1][0] - h / 3).toFixed(1)} ${(pts[i + 1][1] - (m[i + 1] * h) / 3).toFixed(1)}`
        + ` ${pts[i + 1][0].toFixed(1)} ${pts[i + 1][1].toFixed(1)}`;
    }
    return out;
  };

  const renderProfile = (data) => {
    const box = $("[data-hd-profile]");
    const W = Math.max(360, Math.round(box.clientWidth || 800));
    const narrow = W < 620;
    const H = narrow ? 380 : 490;
    const L = narrow ? 36 : 48, R = 10, T = narrow ? 70 : 84, B = 40;
    const row = data.hand_m[PROFILE_ROW];
    const kinds = data.state[PROFILE_ROW];
    const top = 5.5;
    const colW = (W - L - R) / data.cols;
    const base = H - B + 22;
    const x = (col) => L + col * colW;
    const centre = (col) => x(col) + colW / 2;
    const y = (value) => T + (1 - value / top) * (H - T - B);
    const art = Math.min(1, Math.max(0.5, colW / 54));
    const svg = el("svg", {
      viewBox: `0 0 ${W} ${H + 22}`,
      role: "img",
      "aria-label": say("hd.side.aria", { w: metres(data.stage_m) }),
    });
    const defs = el("defs");
    const hatch = el("pattern", { id: "hd-hatch", width: 10, height: 10, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    hatch.append(el("rect", { width: 10, height: 10, fill: "#e5e8e9" }));
    hatch.append(el("line", { x1: 0, y1: 0, x2: 0, y2: 10, stroke: "#727c83", "stroke-width": 3 }));
    const soil = el("pattern", { id: "hd-soil", width: 18, height: 18, patternUnits: "userSpaceOnUse" });
    soil.append(el("rect", { width: 18, height: 18, fill: "#d2a06a" }));
    soil.append(el("circle", { cx: 4, cy: 5, r: 1.4, fill: "#b98a57" }));
    soil.append(el("circle", { cx: 12, cy: 11, r: 1.1, fill: "#b98a57" }));
    soil.append(el("circle", { cx: 7, cy: 15, r: 0.9, fill: "#e2b988" }));
    defs.append(hatch, soil);
    svg.append(defs);
    svg.append(el("rect", { width: W, height: H + 22, class: "hd-p--sky" }));

    for (let value = 0; value <= 5; value += 1) {
      svg.append(el("line", { x1: L, x2: W - R, y1: y(value), y2: y(value), class: "rw-grid" }));
      svg.append(el("text", { x: L - 6, y: y(value) + 4, class: "rw-axis", "text-anchor": "end" }, `${value} m`));
    }

    // Unbroken runs of cells with known ground; outside or missing cells break the bank.
    const known = (col) => row[col] !== null && kinds[col] !== "outside";
    const segments = [];
    let run = [];
    row.forEach((_, col) => {
      if (known(col)) { run.push(col); return; }
      if (run.length) segments.push(run);
      run = [];
    });
    if (run.length) segments.push(run);

    // Decoration first, so water and ground can overlap the house posts.
    [[1, 0], [4, 6], [data.cols - 1, -6]].forEach(([col, dx]) => {
      if (known(col)) treeSymbol(svg, centre(col) + dx * art, y(row[col]), art * (narrow ? 0.7 : 1));
    });
    Object.entries(HOUSES).forEach(([key, house]) => {
      const [houseRow, col] = key.split(":").map(Number);
      const hand = data.hand_m[houseRow][col];
      if (hand === null) return;
      houseSymbol(svg, centre(col), y(hand), art * (narrow ? 0.62 : 0.86));
    });

    // Water only over cells the server marked wet. An edge cell (water = ground) stays dry.
    const wy = y(data.stage_m);
    let start = null;
    for (let col = 0; col <= data.cols; col += 1) {
      const wet = col < data.cols && kinds[col] === "wet";
      if (wet && start === null) start = col;
      if (!wet && start !== null) {
        const a = x(start), b = x(col);
        svg.append(el("rect", { x: a, y: wy, width: b - a, height: base - wy, class: "hd-p--water" }));
        for (let w = a + 12; w + 34 < b; w += 64) {
          svg.append(el("path", { d: `M${w.toFixed(1)} ${(wy + 12).toFixed(1)} q8 -5 16 0 t16 0`, class: "hd-p--wave" }));
        }
        svg.append(el("line", { x1: a, x2: b, y1: wy, y2: wy, class: "hd-p--surface" }));
        start = null;
      }
    }

    segments.forEach((seg) => {
      const x0 = x(seg[0]);
      const x1 = x(seg[seg.length - 1] + 1);
      const pts = [[x0, y(row[seg[0]])], ...seg.map((col) => [centre(col), y(row[col])]), [x1, y(row[seg[seg.length - 1]])]];
      const crest = monotonePath(pts);
      svg.append(el("path", { d: `${crest} L${x1.toFixed(1)} ${base} L${x0.toFixed(1)} ${base} Z`, class: "hd-p--ground" }));
      svg.append(el("path", { d: crest, class: "hd-p--grass" }));
    });

    row.forEach((hand, col) => {
      if (known(col)) return;
      svg.append(el("rect", { x: x(col), y: y(top), width: colW + 0.5, height: base - y(top), class: "hd-p--unknown" }));
    });

    Object.entries(HOUSES).forEach(([key, house]) => {
      const [houseRow, col] = key.split(":").map(Number);
      const hand = data.hand_m[houseRow][col];
      if (hand === null) return;
      houseLabel(svg, centre(col), y(hand), say(house.label),
        houseRow === state.selected.row && col === state.selected.col, art * (narrow ? 0.62 : 0.86));
    });
    svg.append(el("line", { x1: L, x2: W - R, y1: wy, y2: wy, class: "hd-p--level" }));
    const pillW = narrow ? 112 : 150;
    const pillX = Math.min(Math.max(centre(data.channel_col) - pillW / 2, L + 2), W - R - pillW);
    const pillY = Math.max(T - 20, wy - 40);
    svg.append(el("rect", { x: pillX, y: pillY, width: pillW, height: 28, rx: 14, class: "hd-p--pill" }));
    svg.append(el("text", { x: pillX + pillW / 2, y: pillY + 19, class: "hd-p--pill-text", "text-anchor": "middle" }, say("hd.side.water", { w: metres(data.stage_m) })));
    svg.append(el("text", { x: centre(data.channel_col), y: H + 12, class: "hd-p--river-label", "text-anchor": "middle" }, say("hd.side.river")));
    svg.append(el("text", { x: centre(6), y: y(row[6]) + 28, class: "hd-p--bank-label", "text-anchor": "middle" }, say("hd.lowBank")));
    svg.append(el("text", { x: centre(16), y: y(row[16]) + 28, class: "hd-p--bank-label", "text-anchor": "middle" }, say("hd.highBank")));

    const { row: selectedRow, col: selectedCol } = state.selected;
    if (!HOUSES[cellKey(selectedRow, selectedCol)]) {
      // The side view is row 5 of the map. A cell from another row only marks its column,
      // because its own ground height does not sit on this drawn bank.
      const hand = data.hand_m[selectedRow][selectedCol];
      const onRow = selectedRow === PROFILE_ROW && hand !== null;
      const markerY = onRow ? y(hand) : T;
      svg.append(el("line", { x1: centre(selectedCol), x2: centre(selectedCol), y1: onRow ? markerY + 10 : T, y2: base, class: "hd-p--measure" }));
      if (onRow) svg.append(el("circle", { cx: centre(selectedCol), cy: markerY, r: 9, fill: "#fff", class: "hd-p--selected" }));
    }

    // The fictional-data badge is part of the picture, so it survives screenshots.
    const badgeW = narrow ? 190 : 250;
    svg.append(el("rect", { x: L, y: 4, width: badgeW, height: 26, rx: 13, class: "hd-p--badge" }));
    svg.append(el("text", { x: L + badgeW / 2, y: 22, class: "hd-p--badge-text", "text-anchor": "middle" }, say("hd.stripe")));
    box.replaceChildren(svg);
  };

  const renderExample = (data) => {
    const body = $("[data-hd-example]");
    body.replaceChildren();
    data.example.rows.forEach((row) => {
      const tr = document.createElement("tr");
      [
        say(`hd.place.${row.place}`),
        row.hand_m === null ? say("hd.ex.missing") : row.hand_m.toFixed(1),
        row.depth_m === null ? say("hd.ex.unknown") : row.depth_m.toFixed(1),
        say(`hd.state.${row.state}`),
      ].forEach((text) => {
        const td = document.createElement("td");
        td.textContent = text;
        tr.append(td);
      });
      body.append(tr);
    });
  };

  const render = (data) => {
    state.data = data;
    $("[data-hd-confirmed]").textContent = metres(data.stage_m);
    $("[data-hd-request]").textContent = "";
    $("[data-hd-request]").classList.remove("is-error");
    renderAnswer(data);
    renderMap(data);
    renderLegend(data);
    renderProfile(data);
    renderSelectionText(data);
    renderExample(data);
  };

  const ask = async (stage) => {
    const asked = ++state.asked;
    $("[data-hd-request]").textContent = say("hd.loading", { w: metres(Number(stage)) });
    $("[data-hd-request]").classList.remove("is-error");
    try {
      const data = await GRP.request(`/api/v1/pilot/hand-demo?stage_m=${encodeURIComponent(stage)}`);
      if (asked === state.asked) render(data);
    } catch (error) {
      if (asked !== state.asked) return;
      const confirmed = state.data ? metres(state.data.stage_m) : "—";
      $("[data-hd-request]").textContent = say("hd.failed", { w: confirmed, error: error.message });
      $("[data-hd-request]").classList.add("is-error");
    }
  };

  const slider = $("[data-hd-stage]");
  slider.addEventListener("input", () => {
    $("[data-hd-value]").textContent = metres(Number(slider.value));
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(() => ask(slider.value), 120);
  });
  $("[data-hd-numbers]").addEventListener("click", (event) => {
    state.showNumbers = !state.showNumbers;
    event.currentTarget.setAttribute("aria-expanded", String(state.showNumbers));
    if (state.data) renderMap(state.data);
  });
  PilotText.onChange(() => {
    if (state.data) render(state.data);
  });
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => state.data && renderProfile(state.data), 120);
  });

  GRP.me()
    .then((identity) => {
      const isAdmin = identity.is_platform_admin || identity.memberships.some((membership) => membership.role === "admin");
      if (!isAdmin) return;
      $("[data-hd]").hidden = false;
      ask(slider.value);
    })
    .catch(() => {});
})();
