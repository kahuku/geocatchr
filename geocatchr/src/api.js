import { CONFIG } from "./config.js";
import { getAccessToken } from "./storage.js";
import { fetchJson } from "./http.js";

export async function fetchSummary() {
  const accessToken = await getAccessToken();

  const data = await fetchJson(CONFIG.api.summaryUrl, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });

  const rows = Array.isArray(data?.countries)
    ? data.countries.map((item) => ({
        country: item.country,
        totalRounds: item.totalRounds ?? item.rounds_played ?? 0,
        avgDistance: item.avgDistance ?? item.avg_distance ?? 0,
        avgDamage: item.avgDamage ?? item.avg_damage ?? 0
      }))
    : [];

  return { rows };
}

export async function forwardDuelPayload(message, sender) {
  const accessToken = await getAccessToken();

  const body = {
    receivedAt: new Date().toISOString(),
    pageUrl: sender?.tab?.url || null,
    type: message.type,
    payload: message.payload
  };

  const response = await fetch(CONFIG.api.ingestUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`
    },
    body: JSON.stringify(body)
  });

  const responseText = await response.text().catch(() => "");

  if (!response.ok) {
    throw new Error(responseText || `Forwarding failed with status ${response.status}`);
  }

  return {
    status: response.status,
    responseText
  };
}