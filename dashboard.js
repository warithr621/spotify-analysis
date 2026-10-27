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

function rankArtists(fromDay, toDay) {
  const out = [];
  for (const a of DATA.artists) {
    const s = sumDaysInRange(a.days, fromDay, toDay);
    if (s.ms <= 0) continue;
    out.push({ ...a, fm: s.ms, fn: s.n });
  }
  out.sort((a,b)=>b.fm-a.fm||a.name.localeCompare(b.name));
  return out;
}
function rankTracks(fromDay, toDay) {
  const out = [];
  for (const t of DATA.tracks) {
    const s = sumDaysInRange(t.days, fromDay, toDay);
    if (s.ms <= 0) continue;
    out.push({ ...t, fm: s.ms, fn: s.n });
  }
  out.sort((a,b)=>b.fm-a.fm||a.title.localeCompare(b.title));
  return out;
}
function rankAlbums(fromDay, toDay) {
  const out = [];
  for (const al of DATA.albums) {
    const s = sumDaysInRange(al.days, fromDay, toDay);
    if (s.ms <= 0) continue;
    out.push({ ...al, fm: s.ms, fn: s.n });
  }
  out.sort((a,b)=>b.fm-a.fm||a.album.localeCompare(b.album));
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
  renderRace();
  renderArtistWeb();
}

let qArtists='', qAlbums='', qTracks='';
let ra=[], rt=[], ralb=[];

const RANK_CAP = { artists: 160, albums: 200, tracks: 250 };

const streamsLabel = (n) => `${fmtNum(n)} stream${n === 1 ? "" : "s"}`;

/** The muted line under a minutes figure: artists show the day/hour conversion
 *  (they already have a Streams column); albums and tracks show their streams. */
function minutesHint(kind, row) {
  return kind === "artists" ? fmtMin(row.fm / 60000) : streamsLabel(row.fn);
}

function minutesCellHtml(ms, hint) {
  return `<span class="mn">${fmtNum(Math.round(ms / 60000))} min<span class="hint">${hint}</span></span>`;
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

function podiumTileHtml(kind, row, rank) {
  const name = kind === "albums" ? row.album : kind === "tracks" ? row.title : row.name;
  const sub = kind === "artists" ? streamsLabel(row.fn) : row.artist;
  const mainStat = `${fmtNum(Math.round(row.fm / 60000))} min <span class="hint">${minutesHint(kind, row)}</span>`;
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

function listRowHtml(kind, row, rank) {
  const name = kind === "albums" ? row.album : kind === "tracks" ? row.title : row.name;
  const midCell = kind === "artists" ? streamsCellHtml(row.fn) : `<span class="ar">${row.artist}</span>`;
  const lastCell = minutesCellHtml(row.fm, minutesHint(kind, row));
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

function renderRankSection(kind, rows, q) {
  const top3 = rows.slice(0, 3);
  const rest = rows.slice(3, RANK_CAP[kind]);
  document.getElementById(`pod-${kind}`).innerHTML = top3.map((r, i) => podiumTileHtml(kind, r, i + 1)).join("");
  document.getElementById(`list-${kind}`).innerHTML = rest.map((r, i) => listRowHtml(kind, r, i + 4)).join("");
  applySearchVisibility(kind, q);
}

function rebuildRankings(){
  const { fromDay, toDay } = state;

  ra = rankArtists(fromDay, toDay);
  rt = rankTracks(fromDay, toDay);
  ralb = rankAlbums(fromDay, toDay);

  renderRankSection("artists", ra, qArtists);
  renderRankSection("albums", ralb, qAlbums);
  renderRankSection("tracks", rt, qTracks);
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
  wireRaceControls();
  wireWebControls();
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
}

const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- Animated top-artists line race (canvas) ----------
 * One line per artist, value = minutes in a trailing window (or all time). A
 * window of the last `win` days scrolls past as time advances, only each day's
 * top RACE_TOP artists are drawn, and the y-scale/gridlines ease with the data. */

const RACE_TOP = 10;
const RACE_LEAD_DAYS = 3; // empty days kept before the first listen when auto-trimming the start
const RACE_PLAY_SECONDS = 22; // playback length for the whole range, whatever its span
const RACE_FADE_DAYS = 4; // lines ease in/out over this many days around entering/leaving the top list
// Candidates considered per kind (top by total minutes); tracks need a deeper pool
// because a track can top a 30-day window without ranking high all-time.
const RACE_POOL = { artists: 400, albums: 700, tracks: 1500 };

const race = {
  data: null,
  t: 0, // current position, in days since the start of the filtered range
  playing: false,
  raf: 0,
  last: 0,
  kind: "artists", // what is ranked: artists | albums | tracks
  trail: 30, // trailing-window length in days; 0 = all time (cumulative)
  win: 365, // days visible on the x-axis; 0 = the whole range
  scrubbing: false, // user is dragging the slider
  ctx: null,
  w: 0,
  h: 0,
};

/** Cosine-weighted average of `a` around fractional index `index` (eases scale changes). */
function raceAvg(a, index, width) {
  index = Math.min(a.length - 1, Math.max(0, index));
  const s = Math.max(0, Math.ceil(index - width));
  const e = Math.min(Math.floor(index + width), a.length - 1);
  let num = 0,
    den = 0;
  for (let d = s; d <= e; d++) {
    const wt = 0.5 + 0.5 * Math.cos(((d - index) / width) * Math.PI);
    num += a[d] * wt;
    den += wt;
  }
  return den ? num / den : a[Math.round(index)] || 0;
}

function raceUnit(i) {
  return [1, 2, 5][((i % 3) + 3) % 3] * Math.pow(10, Math.floor(i / 3));
}

const raceEntityCache = {};
/** Rankable things of one kind, normalised to {id, label, by, image, days}; `by` is the
 *  artist shown after a track/album title ("Title · Artist"), absent for artists. */
function raceEntities(kind) {
  if (raceEntityCache[kind]) return raceEntityCache[kind];
  const artistImg = new Map(DATA.artists.map((a) => [a.name, a.image]));
  let list;
  if (kind === "tracks") {
    list = DATA.tracks.map((t) => ({ id: t.key, label: t.title, by: t.artist, image: t.image || artistImg.get(t.artist), days: t.days }));
  } else if (kind === "albums") {
    list = DATA.albums.map((al) => ({ id: al.key, label: al.album, by: al.artist, image: al.image || artistImg.get(al.artist), days: al.days }));
  } else {
    list = DATA.artists.map((a) => ({ id: a.name, label: a.name, image: a.image, days: a.days }));
  }
  return (raceEntityCache[kind] = list);
}

/** Stable line colour: hue from a hash of the entity id, so it never changes with settings. */
function raceColorOf(id) {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return `hsl(${(h >>> 0) % 360} 68% 42%)`;
}

function buildRaceData() {
  const lo = dayStrToOff(state.fromDay),
    hi = dayStrToOff(state.toDay);
  const N = hi - lo + 1;
  if (!(N >= 2)) return null;
  const trail = race.trail;
  const pad = trail ? trail - 1 : 0;
  const top = RACE_TOP;

  const pool = [];
  for (const e of raceEntities(race.kind).slice(0, RACE_POOL[race.kind])) {
    const dense = new Float64Array(N + pad); // index 0 = day (lo - pad)
    let any = false,
      before = 0; // "All time" also counts listening from before the selected range
    for (const [i, ms] of e.days) {
      const j = i - (lo - pad);
      if (j >= 0 && j < dense.length) {
        dense[j] += ms;
        any = true;
      } else if (!trail && j < 0) before += ms;
    }
    if (!any && !before) continue;
    const v = new Float32Array(N);
    let run = 0;
    if (trail) {
      for (let j = 0; j < pad; j++) run += dense[j];
      for (let k = 0; k < N; k++) {
        run += dense[k + pad];
        v[k] = run / 60000;
        run -= dense[k];
      }
    } else {
      run = before;
      for (let k = 0; k < N; k++) {
        run += dense[k];
        v[k] = run / 60000;
      }
    }
    pool.push({ name: e.label, by: e.by, image: e.image, color: raceColorOf(e.id), v, shown: new Uint8Array(N) });
  }

  const maxes = new Float32Array(N);
  for (let k = 0; k < N; k++) {
    const best = []; // pool indices, descending by value on day k
    for (let p = 0; p < pool.length; p++) {
      const val = pool[p].v[k];
      if (val <= 0) continue;
      if (best.length >= top && val <= pool[best[best.length - 1]].v[k]) continue;
      let pos = best.length;
      while (pos > 0 && pool[best[pos - 1]].v[k] < val) pos--;
      best.splice(pos, 0, p);
      if (best.length > top) best.pop();
    }
    for (const p of best) pool[p].shown[k] = 1;
    maxes[k] = best.length ? pool[best[0]].v[k] : 0;
  }

  const artists = pool.filter((a) => a.shown.includes(1));
  // Opacity = share of the last RACE_FADE_DAYS days spent in the top list, so a line eases in
  // when it enters and fades out after it drops off instead of popping.
  for (const a of artists) {
    a.alpha = new Float32Array(N);
    let inTop = 0;
    for (let k = 0; k < N; k++) {
      inTop += a.shown[k];
      if (k >= RACE_FADE_DAYS) inTop -= a.shown[k - RACE_FADE_DAYS];
      a.alpha[k] = inTop / RACE_FADE_DAYS;
    }
  }
  // Start just before the first visible listen instead of at the beginning of the range.
  let first = N - 1;
  for (const a of artists) {
    const i = a.shown.indexOf(1);
    if (i >= 0 && i < first) first = i;
  }
  const start = Math.max(0, first - RACE_LEAD_DAYS);
  return { N, lo, start, artists, maxes, scales: null, scalesWin: 0 };
}

const raceImgs = new Map();
/** Loaded image for a url, or null (starts loading it and repaints once ready if paused). */
function raceImg(url) {
  if (!url) return null;
  let im = raceImgs.get(url);
  if (!im) {
    im = new Image();
    im.onload = () => {
      im.ok = true;
      if (!race.playing) drawRace();
    };
    im.src = url;
    raceImgs.set(url, im);
  }
  return im.ok ? im : null;
}

/** Per-day y-axis maximum: the largest value seen in the visible window, smoothed. */
function raceScales(data, win) {
  if (data.scales && data.scalesWin === win) return data.scales;
  const { N, maxes } = data;
  const windowed = new Float32Array(N);
  for (let k = 0; k < N; k++) {
    let m = 0;
    for (let j = Math.max(0, k - win); j <= k; j++) if (maxes[j] > m) m = maxes[j];
    windowed[k] = m;
  }
  const margin = Math.max(3, Math.round(win / 8));
  const out = new Float32Array(N);
  // Eased headroom, but never below the true peak in view (smoothing alone clips spikes).
  for (let k = 0; k < N; k++) out[k] = Math.max(1, raceAvg(windowed, k, margin) * 1.2, windowed[k] * 1.08);
  data.scales = out;
  data.scalesWin = win;
  return out;
}

/** Canvas colours, read once from the page's CSS tokens so the chart matches the theme. */
function raceColors() {
  if (race.colors) return race.colors;
  const css = getComputedStyle(document.documentElement);
  const tok = (name) => css.getPropertyValue(name).trim();
  return (race.colors = { bg: tok("--card-hover"), text: tok("--text"), muted: tok("--muted"), grid: tok("--border-soft") });
}

function raceResize() {
  const canvas = document.getElementById("c-race");
  const host = canvas.parentElement;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  race.w = host.clientWidth;
  race.h = host.clientHeight;
  canvas.width = Math.round(race.w * dpr);
  canvas.height = Math.round(race.h * dpr);
  race.ctx = canvas.getContext("2d");
  race.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawRace() {
  const ctx = race.ctx;
  const data = race.data;
  if (!ctx) return;
  const { w, h } = race;
  const c = raceColors();
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = c.bg;
  ctx.fillRect(0, 0, w, h);
  if (!data) {
    ctx.fillStyle = c.muted;
    ctx.font = "14px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Pick a date range of at least two days.", w / 2, h / 2);
    return;
  }

  const { N, lo, artists } = data;
  const win = race.win || Math.max(1, N - data.start); // 0 = whole range
  const t = Math.min(Math.max(race.t, data.start), N - 1);
  const d = Math.floor(t),
    frac = t - d;
  const fs = Math.max(11, Math.min(16, w / 62));
  const x0 = Math.min(64, w * 0.09) + fs + 6, // + room for the rotated y-axis title
    x1 = w - Math.min(300, w * 0.3); // room for "Title · Artist" labels
  const yTop = Math.max(66, h * 0.15),
    yBot = h - 2 * fs - 24; // date labels, then the x-axis title, below the plot
  const pw = x1 - x0,
    ph = yBot - yTop;

  const scales = raceScales(data, win);
  const scale = Math.max(1, scales[d] + (scales[Math.min(d + 1, N - 1)] - scales[d]) * frac);
  const xOf = (i) => x1 - ((t - i) / win) * pw;
  const yOf = (val) => yBot - (val / scale) * ph;
  const valAt = (a, i) => a.v[i];

  // Horizontal unit lines, cross-fading between neighbouring 1-2-5 units.
  const f = 3 * Math.log10(scale / 4);
  const i0 = Math.floor(f),
    r = f - i0;
  const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
  ctx.font = `${fs - 1}px Inter, system-ui, sans-serif`;
  ctx.textBaseline = "middle";
  const unitLines = (u, alpha) => {
    if (alpha < 0.01) return;
    ctx.globalAlpha = alpha;
    for (let val = 0; val <= scale; val += u) {
      const y = yOf(val);
      ctx.strokeStyle = c.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x1 + 8, y);
      ctx.stroke();
      ctx.fillStyle = c.muted;
      ctx.textAlign = "right";
      ctx.fillText(compact.format(val), x0 - 10, y);
    }
    ctx.globalAlpha = 1;
  };
  unitLines(raceUnit(i0), 1 - r);
  unitLines(raceUnit(i0 + 1), r);

  // Vertical date lines on calendar boundaries that scroll with the data: every month for
  // short views, every quarter for about a year, every January beyond that.
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "center";
  const everyMonths = win <= 120 ? 1 : win <= 420 ? 3 : 12;
  const monthFmt = new Intl.DateTimeFormat(undefined, { timeZone: "UTC", month: "short", year: "numeric" });
  for (let j = Math.max(0, Math.ceil(t - win)); j <= d; j++) {
    const iso = offToDayStr(lo + j);
    if (iso.slice(8, 10) !== "01" || (+iso.slice(5, 7) - 1) % everyMonths) continue;
    const x = xOf(j);
    if (x < x0 + 2) continue;
    ctx.strokeStyle = c.grid;
    ctx.beginPath();
    ctx.moveTo(x, yTop);
    ctx.lineTo(x, yBot);
    ctx.stroke();
    ctx.fillStyle = c.muted;
    ctx.fillText(everyMonths === 12 ? iso.slice(0, 4) : monthFmt.format(new Date(iso + "T00:00:00Z")), x, yBot + fs + 6);
  }

  // Lines (clipped on the left so they slide under the y-axis).
  ctx.save();
  ctx.beginPath();
  ctx.rect(x0, yTop - 6, w - x0, ph + 12);
  ctx.clip();
  ctx.lineWidth = 2.6;
  ctx.lineJoin = "round";
  const labels = [];
  const iStart = Math.max(0, Math.floor(t - win) - 1);
  for (const a of artists) {
    const next = d + 1 < N ? valAt(a, d + 1) : valAt(a, d);
    const head = valAt(a, d) + (next - valAt(a, d)) * frac;
    const pt = (i) => (i > d ? [x1, yOf(head)] : [xOf(i), yOf(valAt(a, i))]);
    ctx.strokeStyle = a.color;
    let open = false; // fully opaque stretches are batched into one path
    ctx.beginPath();
    for (let i = iStart; i <= d; i++) {
      const segAlpha = Math.min(a.alpha[i], a.alpha[Math.min(i + 1, d)]);
      if (segAlpha < 0.02) {
        if (open) ctx.stroke();
        ctx.beginPath();
        open = false;
        continue;
      }
      const [ax, ay] = pt(i),
        [bx, by] = pt(i + 1);
      if (segAlpha > 0.98) {
        if (!open) ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        open = true;
      } else {
        if (open) ctx.stroke();
        open = false;
        ctx.globalAlpha = segAlpha;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.beginPath();
      }
    }
    if (open) ctx.stroke();
    if (a.alpha[d] > 0.05) labels.push({ a, y: yOf(head), val: head, alpha: a.alpha[d] });
  }
  ctx.restore();

  // End-of-line icons and name labels (nudged apart so they stay readable).
  const R = Math.max(10, fs * 0.85);
  labels.sort((p, q) => p.y - q.y);
  const gap = Math.max(fs + 3, 2 * R + 2);
  let prev = -Infinity;
  for (const L of labels) {
    L.ly = Math.max(L.y, prev + gap);
    prev = L.ly;
  }
  for (let i = labels.length - 2; i >= 0; i--) {
    if (labels[i + 1].ly > yBot + 6) labels[i + 1].ly = yBot + 6;
    labels[i].ly = Math.min(labels[i].ly, labels[i + 1].ly - gap);
  }
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.font = `600 ${fs}px Inter, system-ui, sans-serif`;
  const maxLabelW = w - x1 - 2 * R - 20;
  for (const L of labels) {
    const cy = L.ly,
      cx = x1 + R;
    ctx.globalAlpha = L.alpha; // labels fade with their line
    if (Math.abs(cy - L.y) > 1) {
      ctx.strokeStyle = L.a.color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x1, L.y);
      ctx.lineTo(cx, cy);
      ctx.stroke();
    }
    const im = raceImg(L.a.image);
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.clip();
    if (im) {
      const side = Math.min(im.naturalWidth, im.naturalHeight);
      ctx.drawImage(im, (im.naturalWidth - side) / 2, (im.naturalHeight - side) / 2, side, side, cx - R, cy - R, 2 * R, 2 * R);
    } else {
      ctx.fillStyle = L.a.color;
      ctx.fillRect(cx - R, cy - R, 2 * R, 2 * R);
      ctx.fillStyle = "#fff";
      ctx.textAlign = "center";
      ctx.fillText(((L.a.by || L.a.name).trim()[0] || "?").toUpperCase(), cx, cy + 1);
      ctx.textAlign = "left";
    }
    ctx.restore();
    ctx.strokeStyle = L.a.color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.stroke();

    const val = `  ${fmtNum(L.val)}`;
    const by = L.a.by ? ` · ${L.a.by}` : "";
    const fits = (s) => ctx.measureText(s + val).width <= maxLabelW;
    // Shorten the title before the artist, so "Title… · Artist" stays recognisable.
    let name = L.a.name;
    while (name.length > 6 && !fits(name + by)) name = name.slice(0, -2).trimEnd() + "…";
    let label = name + by;
    while (label.length > 4 && !fits(label)) label = label.slice(0, -2).trimEnd() + "…";
    ctx.fillStyle = L.a.color;
    ctx.fillText(label, cx + R + 8, cy);
    ctx.fillStyle = c.muted;
    ctx.fillText(val, cx + R + 8 + ctx.measureText(label).width, cy);
    ctx.globalAlpha = 1;
  }

  // Axes + big date (the controls above already say what is ranked and over what window).
  ctx.strokeStyle = c.muted;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x0, yTop);
  ctx.lineTo(x0, yBot);
  ctx.lineTo(x1 + 8, yBot);
  ctx.stroke();

  // Axis titles. The y title follows "Counted over": each value is the total for the
  // period ending on that day.
  ctx.fillStyle = c.muted;
  ctx.font = `600 ${fs - 1}px Inter, system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillText("Date", (x0 + x1) / 2, h - 10);
  ctx.save();
  ctx.translate(8 + fs / 2, (yTop + yBot) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = "middle";
  ctx.fillText(race.trail ? `Minutes listened, last ${race.trail} days` : "Total minutes listened", 0, 0);
  ctx.restore();

  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillStyle = c.text;
  ctx.font = `600 ${Math.max(22, Math.min(40, w / 26))}px Fraunces, Georgia, serif`;
  const dateStr = new Date(offToDayStr(lo + d) + "T00:00:00Z").toLocaleDateString(undefined, {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  ctx.fillText(dateStr, x0 + 6, yTop - 16);
}

function raceSyncControls() {
  const N = race.data ? race.data.N : 1;
  const scrub = document.getElementById("race-scrub");
  scrub.min = String(race.data ? race.data.start : 0);
  scrub.max = String(N - 1);
  if (!race.scrubbing) scrub.value = String(race.t);
  document.getElementById("race-play").textContent = race.playing ? "Pause" : race.t >= N - 1 ? "Replay" : "Play";
}

/** Date labels under the slider, spanning the (trimmed) playable range. */
function raceRenderTicks() {
  const el = document.getElementById("race-ticks");
  const data = race.data;
  if (!data) {
    el.innerHTML = "";
    return;
  }
  const span = data.N - 1 - data.start;
  const fmt = new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    ...(span > 240 ? {} : { day: "numeric" }),
  });
  const count = 5;
  el.innerHTML = Array.from({ length: count }, (_, i) => {
    const off = data.lo + data.start + Math.round((span * i) / (count - 1));
    return `<span>${fmt.format(new Date(offToDayStr(off) + "T00:00:00Z"))}</span>`;
  }).join("");
}

function raceFrame(now) {
  if (!race.playing || !race.data) return;
  const dt = Math.min((now - race.last) / 1000, 0.1);
  race.last = now;
  const end = race.data.N - 1;
  const speed = Math.max(1, end - race.data.start) / RACE_PLAY_SECONDS; // days per second
  race.t = Math.min(end, race.t + speed * dt);
  if (race.t >= end) race.playing = false;
  drawRace();
  raceSyncControls();
  if (race.playing) race.raf = requestAnimationFrame(raceFrame);
}

function racePlay() {
  if (!race.data) return;
  if (race.t >= race.data.N - 1) race.t = race.data.start; // Replay from the start
  race.playing = true;
  race.last = performance.now();
  cancelAnimationFrame(race.raf);
  race.raf = requestAnimationFrame(raceFrame);
  raceSyncControls();
}

function racePause() {
  race.playing = false;
  cancelAnimationFrame(race.raf);
  raceSyncControls();
}

/** (Re)build for the current date range, resting on the latest day until Play is pressed. */
function renderRace() {
  racePause();
  race.data = buildRaceData();
  race.t = race.data ? race.data.N - 1 : 0;
  raceResize();
  drawRace();
  raceSyncControls();
  raceRenderTicks();
}

/** Rebuild after a kind/trail change, keeping the current position and play state. */
function raceRebuild() {
  const t = race.t;
  race.data = buildRaceData();
  if (!race.data) racePause();
  race.t = race.data ? Math.max(race.data.start, Math.min(t, race.data.N - 1)) : 0;
  drawRace();
  raceSyncControls();
  raceRenderTicks();
}

function wireRaceControls() {
  // Button groups (Rank / Counted over / View): data-race names the race setting, data-v its value.
  document.querySelectorAll(".seg[data-race]").forEach((seg) => {
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-v]");
      if (!btn) return;
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      const key = seg.dataset.race;
      race[key] = key === "kind" ? btn.dataset.v : +btn.dataset.v;
      if (key === "win") drawRace(); // the visible window only changes the drawing
      else raceRebuild();
    });
  });
  document.getElementById("race-play").addEventListener("click", () => (race.playing ? racePause() : racePlay()));
  document.getElementById("race-scrub").addEventListener("input", (e) => {
    race.t = +e.target.value;
    racePause();
    drawRace();
  });
  const scrub = document.getElementById("race-scrub");
  scrub.addEventListener("pointerdown", () => (race.scrubbing = true));
  window.addEventListener("pointerup", () => (race.scrubbing = false));
  window.addEventListener("pointercancel", () => (race.scrubbing = false));
  const host = document.getElementById("c-race").parentElement;
  if ("ResizeObserver" in window) {
    new ResizeObserver(() => {
      if (host.clientWidth && (host.clientWidth !== race.w || host.clientHeight !== race.h)) {
        raceResize();
        drawRace();
      }
    }).observe(host);
  }
}

/* ---------- Artist web (d3 force graph) ---------- */

// Ordered so the first few clusters (the ones that usually exist) contrast most.
const WEB_PALETTE = ["#c026d3", "#6366f1", "#f97316", "#0ea5e9", "#10b981", "#db2777", "#eab308", "#9333ea"];
const WEB_MIN_SHARED = 2;     // sessions two artists must share to be linked
const WEB_LINKS_PER_NODE = 3; // cap on links per artist, once each has its single strongest link
const WEB_LABELS = 15;        // only the top N artists are labelled until highlighted
const WEB_PAIR_STRIDE = 1e4;  // pair key = lo * stride + hi (artist idx < graph_artists.length)

let webSim = null;
let webFit = null;        // re-fits the current graph to the view (Reset view button)
let webPinned = null;     // node whose details stay open after a click
const webPos = new Map(); // last layout position by artist name, so re-renders don't reshuffle

/** Co-listening links among the top `count` artists in the current date range. */
function buildWebGraph(count) {
  const idxByName = new Map((DATA.graph_artists || []).map((name, i) => [name, i]));
  const ranked = rankArtists(state.fromDay, state.toDay).slice(0, count);
  const top = ranked
    .filter((a) => idxByName.has(a.name))
    .map((a, rank) => ({ ...a, rank, idx: idxByName.get(a.name), sess: 0 }));
  const nodeByIdx = new Map(top.map((n) => [n.idx, n]));

  const lo = dayStrToOff(state.fromDay),
    hi = dayStrToOff(state.toDay);
  const pair = new Map();
  for (const [day, arts] of DATA.artist_sessions || []) {
    if (day < lo || day > hi) continue;
    const members = arts.filter((i) => nodeByIdx.has(i)); // arts is sorted ascending
    if (members.length < 2) continue;
    for (const i of members) nodeByIdx.get(i).sess++;
    for (let a = 0; a < members.length; a++) {
      for (let b = a + 1; b < members.length; b++) {
        const k = members[a] * WEB_PAIR_STRIDE + members[b];
        pair.set(k, (pair.get(k) || 0) + 1);
      }
    }
  }

  // Cosine-normalised strength so heavy-rotation artists don't link to everything.
  const cand = [];
  for (const [k, shared] of pair) {
    if (shared < WEB_MIN_SHARED) continue;
    const s = nodeByIdx.get(Math.floor(k / WEB_PAIR_STRIDE)),
      t = nodeByIdx.get(k % WEB_PAIR_STRIDE);
    cand.push({ source: s, target: t, shared, w: shared / Math.sqrt(s.sess * t.sess) });
  }
  cand.sort((x, y) => y.w - x.w);

  // Every artist keeps its strongest link so nobody is orphaned; the rest are added
  // strongest-first only while *both* ends are under the cap. (Letting either end
  // qualify gave the artists everyone co-plays with 20+ links each.)
  const deg = new Map();
  const bump = (n) => deg.set(n, (deg.get(n) || 0) + 1);
  const links = [];
  for (const l of cand) {
    if (deg.has(l.source) && deg.has(l.target)) continue;
    links.push(l);
    bump(l.source);
    bump(l.target);
  }
  const kept = new Set(links);
  for (const l of cand) {
    if (kept.has(l) || deg.get(l.source) >= WEB_LINKS_PER_NODE || deg.get(l.target) >= WEB_LINKS_PER_NODE) continue;
    links.push(l);
    bump(l.source);
    bump(l.target);
  }
  const nodes = top.filter((n) => deg.has(n));

  // Weighted label propagation to colour clusters.
  const adj = new Map(nodes.map((n) => [n, []]));
  for (const l of links) {
    adj.get(l.source).push([l.target, l.w]);
    adj.get(l.target).push([l.source, l.w]);
  }
  const label = new Map(nodes.map((n) => [n, n.rank]));
  for (let it = 0; it < 15; it++) {
    let changed = false;
    for (const n of nodes) {
      const tally = new Map();
      for (const [o, w] of adj.get(n)) tally.set(label.get(o), (tally.get(label.get(o)) || 0) + w);
      let best = label.get(n),
        bw = -1;
      for (const [lab, w] of tally) if (w > bw || (w === bw && lab < best)) { best = lab; bw = w; }
      if (best !== label.get(n)) { label.set(n, best); changed = true; }
    }
    if (!changed) break;
  }
  // Groups ordered by total minutes; each is named after its top artist (nodes are in rank order).
  const groupByLabel = new Map();
  for (const n of nodes) {
    const g = groupByLabel.get(label.get(n)) || { lead: n, size: 0, fm: 0 };
    g.size++;
    g.fm += n.fm;
    groupByLabel.set(label.get(n), g);
    n.group = g;
  }
  const groups = [...groupByLabel.values()].sort((a, b) => b.fm - a.fm);
  groups.forEach((g, i) => (g.color = WEB_PALETTE[i % WEB_PALETTE.length]));

  return { nodes, links, groups, hidden: top.length - nodes.length, untracked: ranked.length - top.length };
}

function renderArtistWeb() {
  const host = document.getElementById("web-host");
  const hint = document.getElementById("web-hint");
  const tip = document.getElementById("web-tip");
  const panel = document.getElementById("web-panel");
  const legend = document.getElementById("web-legend");
  if (webSim) webSim.stop();
  host.innerHTML = "";
  legend.innerHTML = "";
  tip.hidden = true;
  panel.hidden = true;
  webPinned = null;
  webFit = null;

  if (typeof d3 === "undefined") {
    host.innerHTML = `<p class="web-empty">d3 failed to load, so the artist web is unavailable.</p>`;
    return;
  }
  const count = +document.getElementById("web-count").value || 40;
  const { nodes, links, groups, hidden, untracked } = buildWebGraph(count);
  if (nodes.length < 2) {
    host.innerHTML = `<p class="web-empty">Not enough shared listening sessions in this range to link artists.</p>`;
    return;
  }
  const notes = ["Drag · scroll to zoom · click an artist for details"];
  if (hidden) notes.push(`${hidden} unlinked artist${hidden > 1 ? "s" : ""} hidden`);
  if (untracked) notes.push(`${untracked} outside your all-time top ${DATA.graph_artists.length} not tracked`);
  hint.textContent = notes.join(" · ");

  const W = host.clientWidth || 900;
  const H = Math.max(420, Math.min(680, Math.round(W * 0.62)));
  const maxMs = Math.max(...nodes.map((n) => n.fm));
  const radius = (n) => 9 + 24 * Math.sqrt(n.fm / maxMs);

  const svg = d3.select(host).append("svg")
    .attr("viewBox", `0 0 ${W} ${H}`).attr("width", "100%").attr("height", H)
    .attr("role", "img").attr("aria-label", "Force graph of related top artists");
  const defs = svg.append("defs");
  nodes.forEach((n) => {
    if (!n.image) return;
    defs.append("pattern").attr("id", `web-img-${n.idx}`)
      .attr("patternContentUnits", "objectBoundingBox").attr("width", 1).attr("height", 1)
      .append("image").attr("href", n.image).attr("width", 1).attr("height", 1)
      .attr("preserveAspectRatio", "xMidYMid slice");
  });

  const root = svg.append("g");
  const zoom = d3.zoom().scaleExtent([0.2, 4]).on("zoom", (e) => root.attr("transform", e.transform));
  svg.call(zoom);

  // Links inside a cluster take its colour; links between clusters stay neutral (CSS .cross).
  const wMax = Math.max(...links.map((l) => l.w));
  const link = root.append("g").attr("class", "web-links").selectAll("line").data(links).join("line")
    .classed("cross", (l) => l.source.group !== l.target.group)
    .attr("stroke", (l) => l.source.group.color)
    .attr("stroke-width", (l) => 1 + 5 * (l.w / wMax))
    .attr("stroke-opacity", (l) => (l.source.group === l.target.group ? 0.3 + 0.45 * (l.w / wMax) : 0.15 + 0.3 * (l.w / wMax)));

  const node = root.append("g").selectAll("g").data(nodes).join("g").attr("class", "web-node")
    .classed("labeled", (n) => n.rank < WEB_LABELS);
  node.append("circle").attr("r", radius)
    .attr("fill", (n) => (n.image ? `url(#web-img-${n.idx})` : n.group.color))
    .attr("stroke", (n) => n.group.color).attr("stroke-width", 3);
  node.filter((n) => !n.image).append("text").attr("class", "web-initial")
    .attr("text-anchor", "middle").attr("dy", "0.35em")
    .text((n) => (n.name.trim()[0] || "?").toUpperCase());
  node.append("text").attr("class", "web-label").attr("text-anchor", "middle")
    .attr("dy", (n) => radius(n) + 12).text((n) => n.name);

  const nbrs = new Map(nodes.map((n) => [n, new Map()]));
  for (const l of links) {
    nbrs.get(l.source).set(l.target, l);
    nbrs.get(l.target).set(l.source, l);
  }

  const highlight = (n) => {
    const near = n && nbrs.get(n);
    node.classed("dim", (o) => !!n && o !== n && !near.has(o))
      .classed("near", (o) => !!n && (o === n || near.has(o)));
    link.classed("dim", (l) => !!n && l.source !== n && l.target !== n)
      .classed("hot", (l) => !!n && (l.source === n || l.target === n));
  };
  const infoHtml = (n) => {
    const top5 = [...nbrs.get(n)].sort((a, b) => b[1].w - a[1].w).slice(0, 5);
    return `<strong>${escHtml(n.name)}</strong><br>${listeningFriendlyPlain(n.fm / 60000)}` +
      `<div class="web-sub">Played together, of its ${fmtNum(n.sess)} sessions with other top artists:</div>` +
      `<ul>${top5.map(([o, l]) => `<li>${escHtml(o.name)} <span>${l.shared} (${Math.round((100 * l.shared) / n.sess)}%)</span></li>`).join("")}</ul>`;
  };
  const pin = (n) => {
    webPinned = n;
    tip.hidden = true;
    highlight(n);
    panel.hidden = !n;
    if (n) panel.innerHTML = infoHtml(n) + `<button type="button" class="secondary" id="web-open">Open in Artist Dive</button>`;
  };

  node
    .on("mouseenter", (e, n) => {
      if (webPinned) return;
      highlight(n);
      tip.innerHTML = infoHtml(n);
      tip.hidden = false;
    })
    .on("mousemove", (e) => {
      if (webPinned) return;
      const r = tip.offsetParent.getBoundingClientRect();
      tip.style.left = `${Math.min(e.clientX - r.left + 14, r.width - 230)}px`;
      tip.style.top = `${e.clientY - r.top + 14}px`;
    })
    .on("mouseleave", () => {
      if (webPinned) return;
      highlight(null);
      tip.hidden = true;
    })
    .on("click", (e, n) => {
      e.stopPropagation();
      pin(webPinned === n ? null : n);
    });
  svg.on("click", () => pin(null));

  const tick = () => {
    link.attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y)
      .attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y);
    node.attr("transform", (n) => `translate(${n.x},${n.y})`);
  };
  const savePos = () => nodes.forEach((n) => webPos.set(n.name, { x: n.x, y: n.y }));
  for (const n of nodes) {
    const p = webPos.get(n.name);
    if (p) Object.assign(n, p);
  }
  webSim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).distance((l) => 190 - 100 * (l.w / wMax)).strength((l) => 0.15 + 0.6 * (l.w / wMax)))
    .force("charge", d3.forceManyBody().strength(-520))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("x", d3.forceX(W / 2).strength(0.04))
    .force("y", d3.forceY(H / 2).strength(0.06))
    .force("collide", d3.forceCollide((n) => radius(n) + 18))
    .stop();
  // Settle the layout up front rather than animating it in from a jumble.
  webSim.tick(300);
  tick();
  savePos();
  webSim.on("tick", tick).on("end", savePos);

  webFit = (animate) => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) {
      const r = radius(n);
      x0 = Math.min(x0, n.x - r - 30); // side room for labels
      x1 = Math.max(x1, n.x + r + 30);
      y0 = Math.min(y0, n.y - r);
      y1 = Math.max(y1, n.y + r + 16);
    }
    const k = Math.min(1.5, 0.94 * Math.min(W / (x1 - x0), H / (y1 - y0)));
    const t = d3.zoomIdentity.translate(W / 2, H / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    (animate && !prefersReducedMotion() ? svg.transition().duration(400) : svg).call(zoom.transform, t);
  };
  webFit(false);

  node.call(d3.drag()
    .on("start", (e, n) => { if (!e.active) webSim.alphaTarget(0.25).restart(); n.fx = n.x; n.fy = n.y; })
    .on("drag", (e, n) => { n.fx = e.x; n.fy = e.y; })
    .on("end", (e, n) => { if (!e.active) webSim.alphaTarget(0); n.fx = n.fy = null; }));

  legend.innerHTML = groups.slice(0, WEB_PALETTE.length).map((g) =>
    `<span><i style="background:${g.color}"></i>${escHtml(g.lead.name)}${g.size > 1 ? ` &amp; ${g.size - 1} more` : ""}</span>`
  ).join("");
}

function wireWebControls() {
  document.getElementById("web-count").addEventListener("change", renderArtistWeb);
  document.getElementById("web-reset").addEventListener("click", () => webFit && webFit(true));
  document.getElementById("web-panel").addEventListener("click", (e) => {
    if (!e.target.closest("#web-open") || !webPinned) return;
    document.getElementById("artist-input").value = webPinned.name;
    renderArtistChart();
    document.getElementById("artist").scrollIntoView({ behavior: "smooth" });
  });
  let timer = 0,
    lastW = 0;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const w = document.getElementById("web-host").clientWidth;
      if (w && w !== lastW) { lastW = w; renderArtistWeb(); }
    }, 250);
  });
}

bootstrap();
