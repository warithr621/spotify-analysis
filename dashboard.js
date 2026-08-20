const DATA = JSON.parse(document.getElementById("dash-data").textContent);

const DAY_EPOCH = DATA.coverage.day_epoch;

/** Calendar YYYY-MM-DD comparison for date inputs (timezone-agnostic). */
const di = (s) =>
  (!s ? 0 : (s.slice(0, 4) | 0) * 10000 + (s.slice(5, 7) | 0) * 100 + (s.slice(8, 10) | 0));

/** Days since DAY_EPOCH for a calendar date string (matches Python bundle / Central calendar days). */
function dayStrToOff(s) {
  if (!s || !DAY_EPOCH) return 0;
  const [Y, M, D] = s.split("-").map(Number);
  const [Y0, M0, D0] = DAY_EPOCH.split("-").map(Number);
  const t0 = Date.UTC(Y0, M0 - 1, D0);
  const t1 = Date.UTC(Y, M - 1, D);
  return Math.round((t1 - t0) / 86400000);
}

function offToDayStr(off) {
  if (DAY_EPOCH == null || DAY_EPOCH === "") return "";
  const [Y0, M0, D0] = DAY_EPOCH.split("-").map(Number);
  const d = new Date(Date.UTC(Y0, M0 - 1, D0));
  d.setUTCDate(d.getUTCDate() + off);
  return d.toISOString().slice(0, 10);
}

function dayOffFromSeriesRow(row) {
  return typeof row.i === "number" ? row.i : dayStrToOff(row.d);
}

function dayIsoFromSeriesRow(row) {
  return typeof row.i === "number" ? offToDayStr(row.i) : row.d;
}

Chart.defaults.font.family = "Inter, system-ui, sans-serif";
Chart.defaults.color = "#6b4e8a";
Chart.defaults.borderColor = "rgba(42, 10, 74, 0.12)";

function chartLayoutOpts(extra) {
  return Object.assign(
    {
      responsive: true,
      maintainAspectRatio: false,
      devicePixelRatio: Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2.25),
    },
    extra || {}
  );
}

const MINUTES_PER_MONTH = 30.4375 * 24 * 60;

const fmtMin = (m) =>
  m >= 1440 ? `${(m / 1440).toFixed(1)} d` :
  m >= 60 ? `${(m / 60).toFixed(1)} h` : `${m.toFixed(1)} min`;
const fmtNum = (n) => new Intl.NumberFormat().format(Math.round(n));

/** Short human label + exact rounded minutes for UI copy */
function listeningFriendlyWithExact(totalMinutes) {
  const t = Number(totalMinutes);
  if (!Number.isFinite(t) || t <= 0) return `<strong>0 min</strong> <span style="color:var(--muted)">(0 min)</span>`;
  const minsRounded = Math.round(t);
  const daysEquiv = t / 1440;
  let simple;
  if (daysEquiv >= 50) simple = `${(t / MINUTES_PER_MONTH).toFixed(1)} mo`;
  else if (daysEquiv >= 2.5) simple = `${daysEquiv.toFixed(1)} days`;
  else if (t >= 90) simple = `${(t / 60).toFixed(1)} hrs`;
  else simple = `${minsRounded} min`;
  return `<strong>${simple}</strong> <span style="color:var(--muted)">(${fmtNum(minsRounded)} min)</span>`;
}

function listeningFriendlyPlain(totalMinutes) {
  return listeningFriendlyWithExact(totalMinutes).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function sumDaysInRange(dayTuples, fromDay, toDay) {
  if (!dayTuples || !dayTuples.length) return { ms: 0, n: 0 };
  const lo = dayStrToOff(fromDay),
    hi = dayStrToOff(toDay);
  let ms = 0,
    n = 0;
  for (const row of dayTuples) {
    const idx = row[0];
    if (idx >= lo && idx <= hi) {
      ms += row[1];
      n += row[2];
    }
  }
  return { ms, n };
}

/** Filter global daily series */
function daysSlice(fromDay, toDay) {
  const lo = dayStrToOff(fromDay),
    hi = dayStrToOff(toDay);
  return DATA.series.day.filter((row) => {
    const idx = dayOffFromSeriesRow(row);
    return idx >= lo && idx <= hi;
  });
}

function totalsFromDays(days) {
  let ms = 0, n = 0;
  for (const x of days) {
    ms += x.ms;
    n += x.n;
  }
  return { ms, n };
}

function rankArtists(fromDay, toDay, metric = "minutes") {
  const out = [];
  for (const a of DATA.artists) {
    const s = sumDaysInRange(a.days, fromDay, toDay);
    if (s.ms <= 0) continue;
    out.push({ ...a, fm: s.ms, fn: s.n });
  }
  if (metric === "plays") out.sort((a,b)=>b.fn-a.fn||a.name.localeCompare(b.name));
  else out.sort((a,b)=>b.fm-a.fm||a.name.localeCompare(b.name));
  return out;
}
function rankTracks(fromDay, toDay, metric = "minutes") {
  const out = [];
  for (const t of DATA.tracks) {
    const s = sumDaysInRange(t.days, fromDay, toDay);
    if (s.ms <= 0) continue;
    out.push({ ...t, fm: s.ms, fn: s.n });
  }
  if (metric === "plays") out.sort((a,b)=>b.fn-a.fn||a.title.localeCompare(b.title));
  else out.sort((a,b)=>b.fm-a.fm||a.title.localeCompare(b.title));
  return out;
}
function rankAlbums(fromDay, toDay, metric = "minutes") {
  const out = [];
  for (const al of DATA.albums) {
    const s = sumDaysInRange(al.days, fromDay, toDay);
    if (s.ms <= 0) continue;
    out.push({ ...al, fm: s.ms, fn: s.n });
  }
  if (metric === "plays") out.sort((a,b)=>b.fn-a.fn||a.album.localeCompare(b.album));
  else out.sort((a,b)=>b.fm-a.fm||a.album.localeCompare(b.album));
  return out;
}

let state = {
  fromDay: "",
  toDay: "",
  charts: { month: null, year: null, artist: null },
};

function buildMonthSeriesFromDays(days) {
  const map = {};
  for (const x of days) {
    const iso = dayIsoFromSeriesRow(x);
    const m = iso.slice(0, 7);
    map[m] = (map[m] || 0) + x.ms;
  }
  return Object.keys(map)
    .sort()
    .map((m) => ({ m, ms: map[m] }));
}
function buildYearSeriesFromDays(days) {
  const map = {};
  for (const x of days) {
    const iso = dayIsoFromSeriesRow(x);
    const y = iso.slice(0, 4);
    map[y] = (map[y] || 0) + x.ms;
  }
  return Object.keys(map)
    .sort((a, b) => +a - +b)
    .map((y) => ({ y, ms: map[y] }));
}


function renderKpis({ fromDay, toDay }) {
  const days = daysSlice(fromDay, toDay);
  const { ms, n: plays } = totalsFromDays(days);
  const minutesTotal = ms / 60000;
  const uniqDays = days.length;

  const ar = rankArtists(fromDay, toDay);
  const uniqArtistsApprox = ar.length;
  const tr = rankTracks(fromDay, toDay).length;

  const months = buildMonthSeriesFromDays(days);
  let peak = months[0] || { m: "—", ms: 0 };
  for (const x of months) if (x.ms > peak.ms) peak = x;

  const top = ar[0];
  const topSharePct = ms > 0 && top ? (100 * top.fm) / ms : 0;

  const avgPerActiveDay = uniqDays ? minutesTotal / uniqDays : 0;

  const rows = [
    ["Filtered listening time", `${fmtNum(minutesTotal)} min`, plays ? `${fmtNum(plays)} plays` : ""],
    ["Artists in window", fmtNum(uniqArtistsApprox), ""],
    ["Tracks in window", fmtNum(tr), ""],
    ["Peak streaming month", peak.m || "—", peak.m ? fmtMin(peak.ms / 60000) : ""],
    ["#1 artist share in range", `${topSharePct.toFixed(1)}%`, top ? top.name : "—"],
    ["Avg active listening time per day", `${avgPerActiveDay.toFixed(1)} min/day`, ""]
  ];
  const host = document.getElementById("kpi-host");
  host.innerHTML = rows.map(([label,v,hint]) => `
    <div class="kpi">
      <div class="label">${label}</div>
      <div class="val">${v}</div>
      ${hint?`<div class="hint">${hint}</div>`:''}
    </div>`).join("");
}

function renderCharts() {
  const { fromDay, toDay } = state;
  const days = daysSlice(fromDay, toDay);

  const mSeries = buildMonthSeriesFromDays(days);
  const ySeries = buildYearSeriesFromDays(days);

  if (state.charts.month) state.charts.month.destroy();
  state.charts.month = new Chart(document.getElementById("c-month"), {
    type: "line",
    data: {
      labels: mSeries.map((x) => x.m),
      datasets: [
        {
          label: "Minutes",
          data: mSeries.map((x) => +(x.ms / 60000).toFixed(2)),
          borderColor: "#c026d3",
          backgroundColor: "rgba(192,38,211,0.16)",
          fill: true,
          tension: 0.35,
        },
      ],
    },
    options: chartLayoutOpts({
      scales: {
        x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
        y: { ticks: { callback: (v) => `${v}` } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) =>
              `${listeningFriendlyPlain(Number(c.raw))}`,
          },
        },
      },
    }),
  });

  if (state.charts.year) state.charts.year.destroy();
  state.charts.year = new Chart(document.getElementById("c-year"), {
    type: "bar",
    data: {
      labels: ySeries.map((x) => x.y),
      datasets: [
        {
          label: "Minutes",
          data: ySeries.map((x) => +(x.ms / 60000).toFixed(2)),
          backgroundColor: ySeries.map(
            (_, i) => (i % 2 ? "rgba(219,39,119,0.55)" : "rgba(192,38,211,0.55)")
          ),
          borderRadius: 8,
        },
      ],
    },
    options: chartLayoutOpts({
      scales: {
        x: { ticks: { maxRotation: 0 } },
        y: { ticks: { callback: (v) => `${v}` } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) =>
              `${listeningFriendlyPlain(Number(c.raw))}`,
          },
        },
      },
    }),
  });

  rebuildRankings();
  hydrateArtistExplorer();
  renderArtistChart();
}

let qArtists='', qAlbums='', qTracks='';
let ra=[], rt=[], ralb=[];
let metric = "minutes";

const RANK_CAP = { artists: 160, albums: 200, tracks: 250 };

function minutesCellHtml(ms, showHint = true) {
  const mins = Math.round(ms / 60000);
  const hint = showHint ? `<span class="hint">${fmtMin(ms / 60000)}</span>` : "";
  return `<span class="mn">${fmtNum(mins)} min${hint}</span>`;
}

function streamsCellHtml(n) {
  return `<span class="st">${fmtNum(n)}</span>`;
}

function artHtml(image, rank, label) {
  if (image) return `<img class="art" src="${escAttr(image)}" alt="" loading="lazy" />`;
  const initial = (label || "?").trim().slice(0, 1).toUpperCase() || "?";
  return `<div class="art art-fallback c${rank}">${initial}</div>`;
}

function rowSearchKey(kind, name, artist) {
  return `${name} ${kind === "artists" ? "" : artist || ""}`.toLowerCase();
}

function podiumTileHtml(kind, row, rank, metric) {
  const name = kind === "albums" ? row.album : kind === "tracks" ? row.title : row.name;
  const minStat = `${fmtNum(Math.round(row.fm / 60000))} min <span class="hint">${fmtMin(row.fm / 60000)}</span>`;
  const streamStat = `${fmtNum(row.fn)} streams`;
  let sub, mainStat;
  if (kind === "artists") {
    if (metric === "plays") {
      sub = `${fmtNum(Math.round(row.fm / 60000))} min`;
      mainStat = streamStat;
    } else {
      sub = streamStat;
      mainStat = minStat;
    }
  } else {
    sub = row.artist;
    mainStat = metric === "plays" ? streamStat : minStat;
  }
  return `
    <div class="podium-tile" data-rank="${rank}" data-name="${escAttr(rowSearchKey(kind, name, row.artist))}">
      ${artHtml(row.image, rank, name)}
      <div class="podium-meta-col">
        <div class="podium-rank">#${rank}</div>
        <div class="podium-name">${name}</div>
        <div class="podium-sub">${sub}</div>
        <div class="podium-min">${mainStat}</div>
      </div>
    </div>`;
}

function listRowHtml(kind, row, rank, metric) {
  const name = kind === "albums" ? row.album : kind === "tracks" ? row.title : row.name;
  let midCell, lastCell;
  if (kind === "artists") {
    if (metric === "plays") {
      midCell = minutesCellHtml(row.fm, false);
      lastCell = streamsCellHtml(row.fn);
    } else {
      midCell = streamsCellHtml(row.fn);
      lastCell = minutesCellHtml(row.fm, true);
    }
  } else {
    midCell = `<span class="ar">${row.artist}</span>`;
    lastCell = metric === "plays" ? streamsCellHtml(row.fn) : minutesCellHtml(row.fm, true);
  }
  return `
    <div class="row" data-name="${escAttr(rowSearchKey(kind, name, row.artist))}">
      <span class="rk">${rank}</span>
      <span class="nm">${name}</span>
      ${midCell}
      ${lastCell}
    </div>`;
}

function applySearchVisibility(kind, q) {
  const s = q.trim().toLowerCase();
  const card = document.querySelector(`.rank-card[data-section="${kind}"]`);
  if (!card) return;
  card.querySelectorAll(".podium-tile, .list .row:not(.head)").forEach((el) => {
    const hay = el.dataset.name || "";
    el.style.display = !s || hay.includes(s) ? "" : "none";
  });
}

function renderRankSection(kind, rows, q, metric) {
  const top3 = rows.slice(0, 3);
  const rest = rows.slice(3, RANK_CAP[kind]);
  document.getElementById(`pod-${kind}`).innerHTML = top3.map((r, i) => podiumTileHtml(kind, r, i + 1, metric)).join("");
  document.getElementById(`list-${kind}`).innerHTML = rest.map((r, i) => listRowHtml(kind, r, i + 4, metric)).join("");
  applySearchVisibility(kind, q);
}

function updateRankHeaders(metric){
  const a2 = document.getElementById("hd-artists-2");
  const a3 = document.getElementById("hd-artists-3");
  if (a2 && a3) {
    if (metric === "plays") { a2.textContent = "Minutes"; a3.textContent = "Streams"; }
    else { a2.textContent = "Streams"; a3.textContent = "Minutes"; }
  }
  const albumsHd = document.getElementById("hd-albums-metric");
  if (albumsHd) albumsHd.textContent = metric === "plays" ? "Streams" : "Minutes";
  const tracksHd = document.getElementById("hd-tracks-metric");
  if (tracksHd) tracksHd.textContent = metric === "plays" ? "Streams" : "Minutes";
}

function rebuildRankings(){
  const { fromDay, toDay } = state;

  ra = rankArtists(fromDay, toDay, metric);
  rt = rankTracks(fromDay, toDay, metric);
  ralb = rankAlbums(fromDay, toDay, metric);

  renderRankSection("artists", ra, qArtists, metric);
  renderRankSection("albums", ralb, qAlbums, metric);
  renderRankSection("tracks", rt, qTracks, metric);

  updateRankHeaders(metric);
}

function escAttr(v) {
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function hydrateArtistExplorer(){
  const dl = document.getElementById('artist-dl');
  const rows = rankArtists(state.fromDay, state.toDay).slice(0, 500);
  dl.innerHTML = rows.map(a => `<option value="${escAttr(a.name)}"></option>`).join("");
}

function renderArtistChart(){
  const name = (document.getElementById('artist-input').value||'').trim();
  const { fromDay, toDay } = state;

  const artist = DATA.artists.find(a=> a.name===name);

  let monthsFiltered = [];
  if (artist && artist.days && artist.days.length) {
    const lo = dayStrToOff(fromDay),
      hi = dayStrToOff(toDay);
    const dayByMonth = {};
    for (const row of artist.days) {
      const idx = row[0];
      if (idx >= lo && idx <= hi) {
        const ym = offToDayStr(idx).slice(0, 7);
        dayByMonth[ym] = (dayByMonth[ym] || 0) + row[1];
      }
    }
    monthsFiltered = Object.keys(dayByMonth)
      .sort()
      .map((ym) => [ym, dayByMonth[ym]]);
  }

  const blurbEl = document.getElementById("artist-blurb");
  if (artist) {
    const rangeMs = sumDaysInRange(artist.days, fromDay, toDay).ms;
    const rangeMin = rangeMs / 60000;
    blurbEl.innerHTML = `
      <p style="margin:0 0 0.5rem;"><strong>${artist.name}</strong></p>
      <p style="margin:0 0 0.45rem;line-height:1.45;">
        Inside filtered range: ${listeningFriendlyWithExact(rangeMin)}
      </p>
    `;
  } else if (name) {
    blurbEl.innerHTML = `<span style="color:var(--danger)">No exact artist name match.</span>`;
  } else {
    blurbEl.innerHTML =
      `<span style="color:var(--muted)">Choose an artist. Chart bars are listening time per month; tooltips show simplified duration plus exact rounded minutes.</span>`;
  }

  let labels = monthsFiltered.map((m) => m[0]);
  let dataMin = monthsFiltered.map((m) => +(m[1] / 60000).toFixed(2));
  if (artist && labels.length === 0) {
    labels = ["(no months overlap this range)"];
    dataMin = [0];
  }

  if (state.charts.artist) state.charts.artist.destroy();
  state.charts.artist = new Chart(document.getElementById("c-artist"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Listening time by month",
          data: dataMin,
          borderRadius: 8,
          backgroundColor: "rgba(219,39,119,0.5)",
          borderColor: "rgba(219,39,119,0.85)",
          borderWidth: 1,
        },
      ],
    },
    options: chartLayoutOpts({
      scales: {
        x: {
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
          grid: { color: "rgba(192,132,252,0.12)" },
        },
        y: {
          ticks: { callback: (v) => `${v}` },
          grid: { color: "rgba(192,132,252,0.08)" },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: ([it]) => it.label || "",
            label: (c) =>
              `${listeningFriendlyPlain(Number(c.raw))}`,
          },
        },
      },
    }),
  });
}

function formatLatestEventChicago(iso) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso.replace(/\.\d+$/, "Z"));
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "America/Chicago",
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(d);
}

function bootstrap(){
  const tzLab = document.getElementById("tz-label");
  if (tzLab && DATA.coverage.display_timezone) tzLab.textContent = DATA.coverage.display_timezone;

  const earliest =
    DATA.coverage.earliest_day || DATA.coverage.earliest_utc?.slice(0, 10) || "1970-01-01";
  const latest =
    DATA.coverage.latest_day ||
    DATA.coverage.as_of_day_chicago ||
    DATA.coverage.latest_utc?.slice(0, 10) ||
    "1970-01-01";
  const noteEl = document.getElementById("hero-data-note");
  const parts = [];
  if (DATA.coverage.latest_event_utc) {
    parts.push(
      "Latest row in export: " +
        formatLatestEventChicago(DATA.coverage.latest_event_utc)
    );
  }
  if (noteEl) {
    noteEl.textContent = parts.join(" · ");
    noteEl.hidden = parts.length === 0;
  }

  document.getElementById('pills-host').innerHTML =
    `<strong>${fmtNum(DATA.totals.streams)}</strong> plays · ` +
    `<strong>${fmtMin(DATA.totals.minutes)}</strong> listened · ` +
    `<strong>${fmtNum(DATA.totals.unique_artists)}</strong> artists · ` +
    `<strong>${fmtNum(DATA.totals.unique_tracks)}</strong> tracks`;

  state.fromDay = earliest;
  state.toDay = latest;

  document.getElementById('f-from').value = earliest;
  document.getElementById('f-to').value = latest;

  renderKpis({ fromDay: state.fromDay, toDay: state.toDay });
  wireInteractions();
  document.getElementById('artist-input').addEventListener('change', renderArtistChart);
  document.getElementById('artist-input').addEventListener('keyup', renderArtistChart);

  document.getElementById('btn-apply').onclick = ()=>{
    state.fromDay = document.getElementById('f-from').value||earliest;
    state.toDay = document.getElementById('f-to').value||latest;
    if (di(state.fromDay)>di(state.toDay)){ const t = state.fromDay; state.fromDay = state.toDay; state.toDay = t; }
    renderKpis(state);
    renderCharts();
  };
  document.getElementById('btn-reset').onclick = ()=>{
    document.getElementById('f-from').value = earliest;
    document.getElementById('f-to').value = latest;
    document.getElementById('btn-apply').click();
  };

  renderCharts();
  const first = DATA.artists[0]?.name||'';
  if (first) {
    document.getElementById('artist-input').value = first;
    renderArtistChart();
  }

  renderRecentPlays();
  wireRefreshControls();
}

function escHtml(v) {
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatRecentPlayChicago(iso) {
  if (!iso) return "—";
  const s = String(iso);
  const d = new Date(s.endsWith("Z") ? s : s.includes("+") ? s : `${s}Z`);
  if (Number.isNaN(d.getTime())) return escHtml(s);
  const tz = DATA.coverage.display_timezone || "America/Chicago";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: tz,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(d);
}

function renderRecentPlays() {
  const body = document.getElementById("tb-recent");
  if (!body) return;
  const rows = Array.isArray(DATA.recent_streams) ? DATA.recent_streams : [];
  if (!rows.length) {
    body.innerHTML =
      `<tr><td colspan="4" style="padding:1rem;color:var(--muted);text-align:center;">No recent plays in this export.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .slice(0, 10)
    .map((r) => {
      const t = escHtml(r.track || "—");
      const a = escHtml(r.artist || "—");
      const al = escHtml(r.album || "—");
      const ts = formatRecentPlayChicago(r.ts_utc);
      return `<tr><td>${t}</td><td>${a}</td><td>${al}</td><td class="recent-time">${escHtml(ts)}</td></tr>`;
    })
    .join("");
}

function wireRefreshControls() {
  const btn     = document.getElementById("btn-refresh");
  const status  = document.getElementById("refresh-status");
  const barWrap = document.getElementById("refresh-bar-wrap");
  const msg     = document.getElementById("refresh-msg");
  const authBtn = document.getElementById("btn-authorize");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    status.style.display = "block";
    barWrap.style.display = "block";
    msg.className = "";
    msg.textContent = "Refreshing…";
    try {
      const r = await fetch("/api/refresh", { method: "POST" });
      let data = {};
      try { data = await r.json(); } catch {}
      barWrap.style.display = "none";
      if (r.status === 200 && data.ok === true) {
        msg.className = "ok";
        msg.textContent = "✓ " + data.message;
        setTimeout(() => window.location.reload(), 1800);
      } else {
        btn.disabled = false;
        msg.className = "err";
        msg.textContent =
          typeof data.message === "string" ? data.message
          : r.status === 429 ? "You can refresh again after the cooldown."
          : r.statusText || "Unknown error";
      }
    } catch {
      btn.disabled = false;
      barWrap.style.display = "none";
      msg.className = "err";
      msg.textContent = "Could not reach the local server.";
    }
  });

  const pullBtn = document.getElementById("btn-pull");
  if (pullBtn) {
    pullBtn.addEventListener("click", async () => {
      pullBtn.disabled = true;
      status.style.display = "block";
      barWrap.style.display = "block";
      msg.className = "";
      msg.textContent = "Pulling latest data…";
      try {
        const r = await fetch("/api/pull", { method: "POST" });
        let data = {};
        try { data = await r.json(); } catch {}
        barWrap.style.display = "none";
        if (r.status === 200 && data.ok === true) {
          msg.className = "ok";
          msg.textContent = "✓ " + data.message;
          setTimeout(() => window.location.reload(), 1800);
        } else {
          pullBtn.disabled = false;
          msg.className = "err";
          msg.textContent =
            typeof data.message === "string" ? data.message
            : r.statusText || "Unknown error";
        }
      } catch {
        pullBtn.disabled = false;
        barWrap.style.display = "none";
        msg.className = "err";
        msg.textContent = "Could not reach the local server.";
      }
    });
  }

  if (authBtn) {
    authBtn.addEventListener("click", async () => {
      authBtn.disabled = true;
      status.style.display = "block";
      barWrap.style.display = "none";
      msg.className = "";
      msg.textContent = "Opening Spotify authorization in your browser…";
      try {
        const r = await fetch("/api/authorize", { method: "POST" });
        let data = {};
        try { data = await r.json(); } catch {}
        authBtn.disabled = false;
        if (r.status === 200 && data.ok === true) {
          msg.className = "ok";
          msg.textContent = "✓ " + data.message;
        } else {
          msg.className = "err";
          msg.textContent =
            typeof data.message === "string" ? data.message
            : r.statusText || "Unknown error";
        }
      } catch {
        authBtn.disabled = false;
        msg.className = "err";
        msg.textContent = "Could not reach the local server.";
      }
    });
  }
}

function wireInteractions(){
  document.getElementById('srch-artists').addEventListener('input', e=>{ qArtists=e.target.value; applySearchVisibility('artists', qArtists); });
  document.getElementById('srch-albums').addEventListener('input', e=>{ qAlbums=e.target.value; applySearchVisibility('albums', qAlbums); });
  document.getElementById('srch-tracks').addEventListener('input', e=>{ qTracks=e.target.value; applySearchVisibility('tracks', qTracks); });

  const metricSwitch = document.getElementById('metric-switch');
  const metricInput = document.getElementById('metric-toggle-input');
  if (metricSwitch && metricInput) {
    metricInput.addEventListener('change', () => {
      metric = metricInput.checked ? 'plays' : 'minutes';
      metricSwitch.dataset.metric = metric;
      rebuildRankings();
    });
  }
}

bootstrap();
