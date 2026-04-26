/**
 * GeoGuessr Duel Tracker - Popup
 *
 * Responsibilities:
 * - Render auth state
 * - Render user summary table
 * - Render extension version/update status
 * - Send user actions to the service worker
 */

const MESSAGE_TYPES = {
  FETCH_SUMMARY: "FETCH_SUMMARY",
  LOGIN: "LOGIN",
  LOGOUT: "LOGOUT",
  CHECK_FOR_UPDATE: "CHECK_FOR_UPDATE"
};

const elements = {};

document.addEventListener("DOMContentLoaded", initializePopup);

function initializePopup() {
  cacheElements();
  bindEventListeners();

  renderVersionText();
  renderUpdateBanner();
  refreshUpdateStatus();
  renderAuthState();
}

function cacheElements() {
  elements.signedOutView = document.getElementById("signedOutView");
  elements.signedInView = document.getElementById("signedInView");
  elements.output = document.getElementById("output");

  elements.email = document.getElementById("email");
  elements.username = document.getElementById("username");

  elements.loginButton = document.getElementById("login");
  elements.logoutButton = document.getElementById("logout");
  elements.refreshSummaryButton = document.getElementById("refreshSummary");

  elements.summaryTable = document.getElementById("summaryTable");
  elements.summaryTableBody = document.getElementById("summaryTableBody");
  elements.summaryEmpty = document.getElementById("summaryEmpty");

  elements.updateBanner = document.getElementById("updateBanner");
  elements.latestVersionText = document.getElementById("latestVersionText");
  elements.updateLink = document.getElementById("updateLink");
  elements.versionText = document.getElementById("versionText");
}

function bindEventListeners() {
  elements.loginButton.addEventListener("click", handleLogin);
  elements.logoutButton.addEventListener("click", handleLogout);
  elements.refreshSummaryButton.addEventListener("click", refreshSummary);
}

function sendRuntimeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }

      if (!response?.ok) {
        reject(new Error(response?.error || "Request failed"));
        return;
      }

      resolve(response);
    });
  });
}

/* -------------------------------------------------------------------------- */
/* Version + Updates                                                          */
/* -------------------------------------------------------------------------- */

function renderVersionText() {
  elements.versionText.textContent = `v${chrome.runtime.getManifest().version}`;
}

async function renderUpdateBanner() {
  const { updateStatus } = await chrome.storage.local.get(["updateStatus"]);

  if (!updateStatus?.updateAvailable) {
    elements.updateBanner.classList.add("hidden");
    return;
  }

  elements.latestVersionText.textContent = `v${updateStatus.latestVersion}`;
  elements.updateLink.href = updateStatus.downloadUrl || "https://github.com/kahuku/geocatchr";
  elements.updateBanner.classList.remove("hidden");
}

async function refreshUpdateStatus() {
  try {
    await sendRuntimeMessage({ type: MESSAGE_TYPES.CHECK_FOR_UPDATE });
    await renderUpdateBanner();
  } catch (error) {
    console.warn("[Popup] Update check failed:", error);
  }
}

/* -------------------------------------------------------------------------- */
/* Auth                                                                       */
/* -------------------------------------------------------------------------- */

function parseJwt(token) {
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;

    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64));
  } catch (error) {
    console.error("[Popup] Failed to parse JWT:", error);
    return null;
  }
}

async function renderAuthState() {
  const data = await chrome.storage.local.get(["id_token"]);

  if (!data.id_token) {
    showSignedOutView();
    return;
  }

  const claims = parseJwt(data.id_token);

  elements.email.textContent = claims?.email || "(no email)";
  elements.username.textContent =
    claims?.["cognito:username"] ||
    claims?.name ||
    claims?.email ||
    "(unknown user)";

  showSignedInView();
}

function showSignedOutView() {
  elements.signedOutView.classList.remove("hidden");
  elements.signedInView.classList.add("hidden");
  elements.output.textContent = "";
  renderSummaryRows([]);
}

function showSignedInView() {
  elements.signedOutView.classList.add("hidden");
  elements.signedInView.classList.remove("hidden");
}

async function handleLogin() {
  elements.output.textContent = "Starting login...";

  try {
    await sendRuntimeMessage({ type: MESSAGE_TYPES.LOGIN });
    elements.output.textContent = "Signed in successfully.";
    await renderAuthState();
  } catch (error) {
    elements.output.textContent = error.message || "Login failed";
  }
}

async function handleLogout() {
  elements.output.textContent = "Signing out...";

  try {
    await sendRuntimeMessage({ type: MESSAGE_TYPES.LOGOUT });
    elements.output.textContent = "Signed out.";
    renderSummaryRows([]);
    await renderAuthState();
  } catch (error) {
    elements.output.textContent = error.message || "Logout failed";
  }
}

/* -------------------------------------------------------------------------- */
/* Summary                                                                    */
/* -------------------------------------------------------------------------- */

function formatNumber(value, digits = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : "-";
}

function renderSummaryRows(rows) {
  elements.summaryTableBody.innerHTML = "";

  if (!Array.isArray(rows) || rows.length === 0) {
    elements.summaryTable.classList.add("hidden");
    elements.summaryEmpty.classList.remove("hidden");
    elements.summaryEmpty.textContent = "No summary data available.";
    return;
  }

  elements.summaryEmpty.classList.add("hidden");
  elements.summaryTable.classList.remove("hidden");

  for (const row of rows) {
    const tr = document.createElement("tr");

    tr.appendChild(createTableCell(row.country || "-"));
    tr.appendChild(createTableCell(formatNumber(row.totalRounds, 0)));
    tr.appendChild(createTableCell(formatNumber(row.avgDistance, 0)));
    tr.appendChild(createTableCell(formatNumber(row.avgDamage, 1)));

    elements.summaryTableBody.appendChild(tr);
  }
}

function createTableCell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

async function refreshSummary() {
  elements.output.textContent = "Refreshing summary...";

  try {
    const response = await sendRuntimeMessage({ type: MESSAGE_TYPES.FETCH_SUMMARY });
    renderSummaryRows(response.rows || []);
    elements.output.textContent = `Loaded ${response.rows?.length || 0} summary rows.`;
  } catch (error) {
    elements.output.textContent = error.message || "Failed to load summary";
    renderSummaryRows([]);
  }
}