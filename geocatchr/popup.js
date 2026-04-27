/**
 * GeoCatchr — Popup
 * Handles auth state, summary table with sorting, country flags, stat pills.
 */

const MSG = {
  FETCH_SUMMARY:    "FETCH_SUMMARY",
  LOGIN:            "LOGIN",
  LOGOUT:           "LOGOUT",
  CHECK_FOR_UPDATE: "CHECK_FOR_UPDATE",
};

/* Country name → flag emoji map (top GeoGuessr countries) */
const FLAGS = {
  "Afghanistan": "🇦🇫", "Albania": "🇦🇱", "Algeria": "🇩🇿", "Andorra": "🇦🇩",
  "Angola": "🇦🇴", "Argentina": "🇦🇷", "Armenia": "🇦🇲", "Australia": "🇦🇺",
  "Austria": "🇦🇹", "Azerbaijan": "🇦🇿", "Bangladesh": "🇧🇩", "Belarus": "🇧🇾",
  "Belgium": "🇧🇪", "Belize": "🇧🇿", "Benin": "🇧🇯", "Bhutan": "🇧🇹",
  "Bolivia": "🇧🇴", "Bosnia and Herzegovina": "🇧🇦", "Botswana": "🇧🇼",
  "Brazil": "🇧🇷", "Bulgaria": "🇧🇬", "Burkina Faso": "🇧🇫", "Cambodia": "🇰🇭",
  "Cameroon": "🇨🇲", "Canada": "🇨🇦", "Chile": "🇨🇱", "China": "🇨🇳",
  "Colombia": "🇨🇴", "Croatia": "🇭🇷", "Cuba": "🇨🇺", "Cyprus": "🇨🇾",
  "Czechia": "🇨🇿", "Czech Republic": "🇨🇿", "Denmark": "🇩🇰", "Dominican Republic": "🇩🇴",
  "Ecuador": "🇪🇨", "Egypt": "🇪🇬", "El Salvador": "🇸🇻", "Estonia": "🇪🇪",
  "Ethiopia": "🇪🇹", "Finland": "🇫🇮", "France": "🇫🇷", "Georgia": "🇬🇪",
  "Germany": "🇩🇪", "Ghana": "🇬🇭", "Greece": "🇬🇷", "Guatemala": "🇬🇹",
  "Honduras": "🇭🇳", "Hong Kong": "🇭🇰", "Hungary": "🇭🇺", "Iceland": "🇮🇸",
  "India": "🇮🇳", "Indonesia": "🇮🇩", "Iran": "🇮🇷", "Iraq": "🇮🇶",
  "Ireland": "🇮🇪", "Israel": "🇮🇱", "Italy": "🇮🇹", "Japan": "🇯🇵",
  "Jordan": "🇯🇴", "Kazakhstan": "🇰🇿", "Kenya": "🇰🇪", "Kosovo": "🇽🇰",
  "Kuwait": "🇰🇼", "Kyrgyzstan": "🇰🇬", "Laos": "🇱🇦", "Latvia": "🇱🇻",
  "Lebanon": "🇱🇧", "Lithuania": "🇱🇹", "Luxembourg": "🇱🇺", "Malaysia": "🇲🇾",
  "Maldives": "🇲🇻", "Malta": "🇲🇹", "Mexico": "🇲🇽", "Moldova": "🇲🇩",
  "Mongolia": "🇲🇳", "Montenegro": "🇲🇪", "Morocco": "🇲🇦", "Mozambique": "🇲🇿",
  "Nepal": "🇳🇵", "Netherlands": "🇳🇱", "New Zealand": "🇳🇿", "Nicaragua": "🇳🇮",
  "Nigeria": "🇳🇬", "North Macedonia": "🇲🇰", "Norway": "🇳🇴", "Oman": "🇴🇲",
  "Pakistan": "🇵🇰", "Palestine": "🇵🇸", "Panama": "🇵🇦", "Paraguay": "🇵🇾",
  "Peru": "🇵🇪", "Philippines": "🇵🇭", "Poland": "🇵🇱", "Portugal": "🇵🇹",
  "Puerto Rico": "🇵🇷", "Qatar": "🇶🇦", "Romania": "🇷🇴", "Russia": "🇷🇺",
  "Rwanda": "🇷🇼", "Saudi Arabia": "🇸🇦", "Senegal": "🇸🇳", "Serbia": "🇷🇸",
  "Singapore": "🇸🇬", "Slovakia": "🇸🇰", "Slovenia": "🇸🇮", "Somalia": "🇸🇴",
  "South Africa": "🇿🇦", "South Korea": "🇰🇷", "Spain": "🇪🇸", "Sri Lanka": "🇱🇰",
  "Sweden": "🇸🇪", "Switzerland": "🇨🇭", "Taiwan": "🇹🇼", "Tajikistan": "🇹🇯",
  "Tanzania": "🇹🇿", "Thailand": "🇹🇭", "Tunisia": "🇹🇳", "Turkey": "🇹🇷",
  "Turkmenistan": "🇹🇲", "Uganda": "🇺🇬", "Ukraine": "🇺🇦",
  "United Arab Emirates": "🇦🇪", "United Kingdom": "🇬🇧", "United States": "🇺🇸",
  "Uruguay": "🇺🇾", "Uzbekistan": "🇺🇿", "Venezuela": "🇻🇪", "Vietnam": "🇻🇳",
  "Yemen": "🇾🇪", "Zambia": "🇿🇲", "Zimbabwe": "🇿🇼",
};

function getFlag(country) {
  return FLAGS[country] || "🌐";
}

/* ── State ── */
let currentRows = [];
let sortKey = "dmg"; // "dmg" | "dist" | "rounds"

const el = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  cache();
  bindEvents();
  renderVersion();
  renderUpdateBanner();
  refreshUpdateCheck();

  const signedIn = await renderAuth();
  if (signedIn) await loadSummary();
}

/* ── Element Cache ── */
function cache() {
  el.signedOut      = document.getElementById("signedOutView");
  el.signedIn       = document.getElementById("signedInView");
  el.output         = document.getElementById("output");
  el.email          = document.getElementById("email");
  el.username       = document.getElementById("username");
  el.userInitials   = document.getElementById("userInitials");
  el.loginBtn       = document.getElementById("login");
  el.logoutBtn      = document.getElementById("logout");
  el.refreshBtn     = document.getElementById("refreshSummary");
  el.summaryTable   = document.getElementById("summaryTable");
  el.summaryBody    = document.getElementById("summaryTableBody");
  el.summaryEmpty   = document.getElementById("summaryEmpty");
  el.updateBanner   = document.getElementById("updateBanner");
  el.latestVersion  = document.getElementById("latestVersionText");
  el.updateLink     = document.getElementById("updateLink");
  el.versionText    = document.getElementById("versionText");
  el.statPills      = document.getElementById("statPills");
  el.statCountries  = document.getElementById("statCountries");
  el.statRounds     = document.getElementById("statRounds");
  el.statWorstDmg   = document.getElementById("statWorstDmg");
  el.sortControls   = document.getElementById("sortControls");
}

function bindEvents() {
  el.loginBtn.addEventListener("click", handleLogin);
  el.logoutBtn.addEventListener("click", handleLogout);
  el.refreshBtn.addEventListener("click", loadSummary);

  el.sortControls.addEventListener("click", (e) => {
    const btn = e.target.closest(".sort-pill");
    if (!btn) return;
    sortKey = btn.dataset.sort;
    el.sortControls.querySelectorAll(".sort-pill").forEach(b => b.classList.remove("on"));
    btn.classList.add("on");
    renderRows(currentRows);
  });
}

/* ── Messaging ── */
function sendMsg(msg) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(msg, (res) => {
      if (chrome.runtime.lastError) { reject(new Error(chrome.runtime.lastError.message)); return; }
      if (!res?.ok) { reject(new Error(res?.error || "Request failed")); return; }
      resolve(res);
    });
  });
}

/* ── Version & Updates ── */
function renderVersion() {
  el.versionText.textContent = `v${chrome.runtime.getManifest().version}`;
}

async function renderUpdateBanner() {
  const { updateStatus } = await chrome.storage.local.get(["updateStatus"]);
  if (!updateStatus?.updateAvailable) { el.updateBanner.classList.add("hidden"); return; }
  el.latestVersion.textContent = `v${updateStatus.latestVersion}`;
  el.updateLink.href = updateStatus.downloadUrl || "https://github.com/kahuku/geocatchr";
  el.updateBanner.classList.remove("hidden");
}

async function refreshUpdateCheck() {
  try { await sendMsg({ type: MSG.CHECK_FOR_UPDATE }); await renderUpdateBanner(); }
  catch (e) { console.warn("[Popup] Update check failed:", e); }
}

/* ── Auth ── */
function parseJwt(token) {
  try {
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64));
  } catch { return null; }
}

async function renderAuth() {
  const { id_token } = await chrome.storage.local.get(["id_token"]);
  if (!id_token) { showView("out"); return false; }

  const claims = parseJwt(id_token);
  const name = claims?.["cognito:username"] || claims?.name || claims?.email || "Player";
  const email = claims?.email || "";

  el.username.textContent = name;
  el.email.textContent = email;
  el.userInitials.textContent = name.slice(0, 2);

  showView("in");
  return true;
}

function showView(which) {
  el.signedOut.classList.toggle("hidden", which !== "out");
  el.signedIn.classList.toggle("hidden",  which !== "in");
  el.output.textContent = "";
  if (which === "out") renderRows([]);
}

async function handleLogin() {
  setStatus("Connecting to GeoGuessr…");
  try {
    await sendMsg({ type: MSG.LOGIN });
    const ok = await renderAuth();
    if (ok) await loadSummary();
    setStatus("Signed in.", "ok");
  } catch (e) {
    setStatus(e.message || "Login failed.", "err");
  }
}

async function handleLogout() {
  setStatus("Signing out…");
  try {
    await sendMsg({ type: MSG.LOGOUT });
    renderRows([]);
    await renderAuth();
    setStatus("Signed out.", "ok");
  } catch (e) {
    setStatus(e.message || "Logout failed.", "err");
  }
}

/* ── Summary ── */
async function loadSummary() {
  el.refreshBtn.classList.add("loading");
  setStatus("Refreshing summary…");
  try {
    const res = await sendMsg({ type: MSG.FETCH_SUMMARY });
    currentRows = res.rows || [];
    renderRows(currentRows);
    renderStatPills(currentRows);
    setStatus(`Loaded ${currentRows.length} countr${currentRows.length === 1 ? "y" : "ies"}.`, "ok");
  } catch (e) {
    setStatus(e.message || "Failed to load summary.", "err");
    renderRows([]);
    if (isAuthErr(e)) renderAuth();
  } finally {
    el.refreshBtn.classList.remove("loading");
  }
}

function isAuthErr(e) {
  const m = String(e?.message || e || "").toLowerCase();
  return m.includes("not signed in") || m.includes("session expired") || m.includes("unauthorized") || m.includes("401");
}

function fmt(v, digits = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function fmtDist(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n >= 1000 ? (n / 1000).toFixed(1) + "k" : n.toFixed(0);
}

/* Sort rows by current sortKey */
function sorted(rows) {
  return [...rows].sort((a, b) => {
    if (sortKey === "dmg")    return Number(a.avgDamage) - Number(b.avgDamage); // most negative first
    if (sortKey === "dist")   return Number(b.avgDistance) - Number(a.avgDistance);
    if (sortKey === "rounds") return Number(b.totalRounds) - Number(a.totalRounds);
    return 0;
  });
}

function dmgClass(dmg) {
  const v = Number(dmg);
  if (v <= -1500) return "dmg-high";
  if (v <= -800)  return "dmg-mid";
  if (v < 0)      return "dmg-low";
  return "dmg-pos";
}

function barColor(dmg) {
  const v = Number(dmg);
  if (v <= -1500) return "rgba(255,77,77,0.07)";
  if (v <= -800)  return "rgba(245,158,11,0.07)";
  if (v < 0)      return "rgba(110,179,255,0.06)";
  return "rgba(0,217,126,0.06)";
}

function renderRows(rows) {
  el.summaryBody.innerHTML = "";

  if (!Array.isArray(rows) || rows.length === 0) {
    el.summaryTable.classList.add("hidden");
    el.summaryEmpty.classList.remove("hidden");
    el.statPills.classList.add("hidden");
    return;
  }

  el.summaryEmpty.classList.add("hidden");
  el.summaryTable.classList.remove("hidden");

  const data = sorted(rows);
  const maxAbsDmg = Math.max(...data.map(r => Math.abs(Number(r.avgDamage) || 0)), 1);

  data.forEach((row, i) => {
    const dmg = Number(row.avgDamage) || 0;
    const pct = Math.min(100, (Math.abs(dmg) / maxAbsDmg) * 100).toFixed(1);
    const color = barColor(dmg);
    const flag = getFlag(row.country || "");

    const div = document.createElement("div");
    div.className = "c-row";
    div.style.cssText = `--bar:${pct}%;--bar-color:${color};animation-delay:${i * 30}ms`;
    div.innerHTML = `
      <div class="c-name">
        <span class="flag">${flag}</span>
        <span class="cname-text">${row.country || "—"}</span>
      </div>
      <div class="c-rounds">${fmt(row.totalRounds)}</div>
      <div class="c-dist">${fmtDist(row.avgDistance)}</div>
      <div class="c-dmg ${dmgClass(dmg)}">${fmt(dmg, 1)}</div>
    `;
    el.summaryBody.appendChild(div);
  });
}

function renderStatPills(rows) {
  if (!rows || rows.length === 0) { el.statPills.classList.add("hidden"); return; }
  el.statPills.classList.remove("hidden");

  const totalRounds = rows.reduce((s, r) => s + (Number(r.totalRounds) || 0), 0);
  const worstDmg = Math.min(...rows.map(r => Number(r.avgDamage) || 0));

  el.statCountries.textContent = rows.length;
  el.statRounds.textContent = totalRounds;
  el.statWorstDmg.textContent = worstDmg.toFixed(0);
}

/* ── Status Bar ── */
function setStatus(msg, type = "") {
  el.output.className = "status-bar" + (type ? ` ${type}` : "");
  el.output.innerHTML = msg
    ? `<span class="s-dot"></span>${msg}`
    : "";
}
