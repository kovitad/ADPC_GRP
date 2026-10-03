// Pilot Phase B1: the HAND flood-depth practice example, on made-up ground.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const SVG = "http://www.w3.org/2000/svg";
  const PROFILE_ROW = 6;
  const state = { data: null, asked: 0, timer: null };
  const say = PilotText.t;

  const metres = (value) => `${(Math.round(value * 10) / 10).toFixed(1)} m`;

  // Depth bands for colour only; the numbers come from the server's rule.
  const band = (data, r, c) => {
    const kind = data.state[r][c];
    if (kind !== "wet") return kind;
    const depth = data.depth_m[r][c];
    if (depth <= 1) return "wet-1";
    if (depth <= 2) return "wet-2";
    return "wet-3";
  };

  const LEGEND = ["wet-1", "wet-2", "wet-3", "edge", "dry", "unknown", "outside"];

  const describe = (data, r, c) => {
    const hand = data.hand_m[r][c];
    const kind = data.state[r][c];
    const water = metres(data.stage_m);
    if (kind === "outside") return say("hd.cell.outside");
    if (kind === "unknown") return say("hd.cell.unknown");
    const ground = say("hd.cell.ground", { h: metres(hand) });
    if (kind === "wet") return say("hd.cell.wet", { ground, w: water, d: metres(data.depth_m[r][c]) });
    if (kind === "edge") return say("hd.cell.edge", { ground, w: water });
    return say("hd.cell.dry", { ground, w: water });
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

  const renderMap = (data) => {
    const map = $("[data-hd-map]");
    map.style.gridTemplateColumns = `repeat(${data.cols}, 1fr)`;
    map.replaceChildren();
    const showNumbers = $("[data-hd-numbers]").checked;
    data.state.forEach((row, r) => row.forEach((_, c) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = `hd__sq hd-c--${band(data, r, c)}`;
      if (c === data.channel_col && data.state[r][c] !== "outside") cell.classList.add("is-channel");
      const text = describe(data, r, c);
      cell.setAttribute("aria-label", text);
      cell.title = text;
      const hand = data.hand_m[r][c];
      if (showNumbers && hand !== null && data.state[r][c] !== "outside") cell.textContent = hand.toFixed(1);
      const show = () => { $("[data-hd-cell]").textContent = text; };
      cell.addEventListener("mouseenter", show);
      cell.addEventListener("focus", show);
      cell.addEventListener("click", show);
      map.append(cell);
    }));
  };

  const renderAnswer = (data) => {
    const n = data.counts;
    const known = n.wet + n.edge + n.dry;
    const water = metres(data.stage_m);
    const parts = [];
    if (n.wet === 0) {
      parts.push(say("hd.ans.none", { w: water }));
    } else {
      parts.push(
        say("hd.ans.some", { w: water, wet: n.wet, known })
        + (data.deep_cells ? say("hd.ans.deep", { deep: data.deep_cells }) : say("hd.ans.shallow")),
      );
      parts.push(say("hd.ans.deepest", { d: metres(data.deepest_m) }));
    }
    if (n.unknown) parts.push(say("hd.ans.unknown", { n: n.unknown }));
    $("[data-hd-answer]").textContent = parts.join(" ");
  };

  const el = (name, attrs = {}, text) => {
    const node = document.createElementNS(SVG, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const renderProfile = (data) => {
    const box = $("[data-hd-profile]");
    const W = Math.max(320, Math.round(box.clientWidth || 640));
    const H = 200, L = 40, R = 10, T = 16, B = 26;
    const row = data.hand_m[PROFILE_ROW];
    const top = Math.max(5, ...row.filter((v) => v !== null)) + 0.5;
    const colW = (W - L - R) / data.cols;
    const x = (c) => L + c * colW;
    const y = (v) => T + (1 - v / top) * (H - T - B);
    const svg = el("svg", {
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": say("hd.side.aria", { w: metres(data.stage_m) }),
    });
    for (let v = 0; v <= Math.floor(top); v += 1) {
      svg.append(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "rw-grid" }));
      svg.append(el("text", { x: L - 6, y: y(v) + 4, class: "rw-axis", "text-anchor": "end" }, `${v} m`));
    }
    row.forEach((hand, c) => {
      if (hand === null || data.state[PROFILE_ROW][c] === "outside") {
        svg.append(el("rect", { x: x(c), y: T, width: colW, height: H - T - B, class: "hd-p--gap" }));
        return;
      }
      if (hand < data.stage_m) {
        svg.append(el("rect", { x: x(c), y: y(data.stage_m), width: colW + 0.5, height: y(hand) - y(data.stage_m), class: "hd-p--water" }));
      }
      svg.append(el("rect", { x: x(c), y: y(hand), width: colW + 0.5, height: H - B - y(hand), class: "hd-p--ground" }));
    });
    svg.append(el("line", { x1: L, x2: W - R, y1: y(data.stage_m), y2: y(data.stage_m), class: "hd-p--level" }));
    // Label the water line above the channel, where there is always open sky above it.
    svg.append(el("text", { x: x(data.channel_col) + colW / 2, y: Math.max(T + 10, y(data.stage_m) - 6), class: "hd-p--label", "text-anchor": "middle" }, say("hd.side.water", { w: metres(data.stage_m) })));
    svg.append(el("text", { x: x(data.channel_col) + colW / 2, y: H - 8, class: "rw-axis", "text-anchor": "middle" }, say("hd.side.river")));
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
    $("[data-hd-value]").textContent = data.stage_m.toFixed(1);
    renderAnswer(data);
    renderMap(data);
    renderLegend(data);
    renderProfile(data);
    renderExample(data);
  };

  const ask = async (stage) => {
    const asked = ++state.asked;
    try {
      const data = await GRP.request(`/api/v1/pilot/hand-demo?stage_m=${encodeURIComponent(stage)}`);
      if (asked === state.asked) render(data);
    } catch (error) {
      if (asked === state.asked) $("[data-hd-answer]").textContent = error.message;
    }
  };

  const slider = $("[data-hd-stage]");
  slider.addEventListener("input", () => {
    $("[data-hd-value]").textContent = Number(slider.value).toFixed(1);
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(() => ask(slider.value), 150);
  });
  $("[data-hd-numbers]").addEventListener("change", () => state.data && renderMap(state.data));
  PilotText.onChange(() => {
    if (!state.data) return;
    render(state.data);
    $("[data-hd-cell]").textContent = say("hd.cellPrompt");
  });
  window.addEventListener("resize", () => state.data && renderProfile(state.data));

  GRP.me()
    .then((identity) => {
      const isAdmin = identity.is_platform_admin || identity.memberships.some((m) => m.role === "admin");
      if (!isAdmin) return;
      $("[data-hd]").hidden = false;
      ask(slider.value);
    })
    .catch(() => {});
})();
