console.log("[Popup] popup.js loaded");

function parseJwt(token) {
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;

    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(base64);
    return JSON.parse(json);
  } catch (err) {
    console.error("[Popup] Failed to parse JWT:", err);
    return null;
  }
}

function formatNumber(value, digits = 0) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(digits);
}

function renderSummaryRows(rows) {
  const summaryTable = document.getElementById("summaryTable");
  const summaryTableBody = document.getElementById("summaryTableBody");
  const summaryEmpty = document.getElementById("summaryEmpty");

  summaryTableBody.innerHTML = "";

  if (!Array.isArray(rows) || rows.length === 0) {
    summaryTable.classList.add("hidden");
    summaryEmpty.classList.remove("hidden");
    summaryEmpty.textContent = "No summary data available.";
    return;
  }

  summaryEmpty.classList.add("hidden");
  summaryTable.classList.remove("hidden");

  for (const row of rows) {
    const tr = document.createElement("tr");

    const countryTd = document.createElement("td");
    countryTd.textContent = row.country || "-";

    const roundsTd = document.createElement("td");
    roundsTd.textContent = formatNumber(row.totalRounds, 0);

    const avgDistTd = document.createElement("td");
    avgDistTd.textContent = formatNumber(row.avgDistance, 0);

    const avgDamageTd = document.createElement("td");
    avgDamageTd.textContent = formatNumber(row.avgDamage, 1);

    tr.appendChild(countryTd);
    tr.appendChild(roundsTd);
    tr.appendChild(avgDistTd);
    tr.appendChild(avgDamageTd);

    summaryTableBody.appendChild(tr);
  }
}

async function renderAuthState() {
  const signedOutView = document.getElementById("signedOutView");
  const signedInView = document.getElementById("signedInView");
  const output = document.getElementById("output");
  const emailEl = document.getElementById("email");
  const usernameEl = document.getElementById("username");

  const data = await chrome.storage.local.get([
    "id_token",
    "access_token",
    "refresh_token"
  ]);

  console.log("[Popup] Stored auth data:", data);

  if (!data.id_token) {
    signedOutView.classList.remove("hidden");
    signedInView.classList.add("hidden");
    output.textContent = "";
    renderSummaryRows([]);
    return;
  }

  const claims = parseJwt(data.id_token);
  console.log("[Popup] Parsed ID token claims:", claims);

  signedOutView.classList.add("hidden");
  signedInView.classList.remove("hidden");

  emailEl.textContent = claims?.email || "(no email)";
  usernameEl.textContent =
    claims?.["cognito:username"] ||
    claims?.name ||
    claims?.email ||
    "(unknown user)";
}

async function refreshSummary() {
  const output = document.getElementById("output");
  output.textContent = "Refreshing summary...";

  chrome.runtime.sendMessage({ type: "FETCH_SUMMARY" }, (response) => {
    console.log("[Popup] FETCH_SUMMARY response:", response);
    console.log("[Popup] runtime.lastError:", chrome.runtime.lastError);

    if (chrome.runtime.lastError) {
      output.textContent = `Runtime error: ${chrome.runtime.lastError.message}`;
      return;
    }

    if (!response?.ok) {
      output.textContent = response?.error || "Failed to load summary";
      renderSummaryRows([]);
      return;
    }

    renderSummaryRows(response.rows || []);
    output.textContent = `Loaded ${response.rows?.length || 0} summary rows.`;
  });
}

document.getElementById("login").addEventListener("click", async () => {
  console.log("[Popup] Sign in button clicked");

  const output = document.getElementById("output");
  output.textContent = "Starting login...";

  chrome.runtime.sendMessage({ type: "LOGIN" }, async (response) => {
    console.log("[Popup] LOGIN response:", response);
    console.log("[Popup] runtime.lastError:", chrome.runtime.lastError);

    if (chrome.runtime.lastError) {
      output.textContent = `Runtime error: ${chrome.runtime.lastError.message}`;
      return;
    }

    if (!response?.ok) {
      output.textContent = response?.error || "Login failed";
      return;
    }

    output.textContent = "Signed in successfully.";
    await renderAuthState();
  });
});

document.getElementById("logout").addEventListener("click", async () => {
  console.log("[Popup] Sign out button clicked");

  const output = document.getElementById("output");
  output.textContent = "Signing out...";

  chrome.runtime.sendMessage({ type: "LOGOUT" }, async (response) => {
    console.log("[Popup] LOGOUT response:", response);
    console.log("[Popup] runtime.lastError:", chrome.runtime.lastError);

    if (chrome.runtime.lastError) {
      output.textContent = `Runtime error: ${chrome.runtime.lastError.message}`;
      return;
    }

    if (!response?.ok) {
      output.textContent = response?.error || "Logout failed";
      return;
    }

    output.textContent = "Signed out.";
    renderSummaryRows([]);
    await renderAuthState();
  });
});

document.addEventListener("DOMContentLoaded", () => {
  renderAuthState();

  document.getElementById("refreshSummary").addEventListener("click", () => {
    refreshSummary();
  });
});