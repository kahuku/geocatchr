import { CONFIG } from "./config.js";
import { STORAGE_KEYS } from "./constants.js";
import { getValidAccessToken } from "./storage.js";
import { fetchJson } from "./http.js";

export async function fetchSummary() {
  const accessToken = await getValidAccessToken();

  const data = await fetchJson(CONFIG.api.summaryUrl, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });

  const rows = Array.isArray(data?.countries)
    ? data.countries.map((item) => ({
        country: item.countryName || item.country || item.countryCode || "-",
        countryCode: item.countryCode || item.country || "-",
        totalRounds: item.totalRounds ?? item.rounds_played ?? 0,
        avgDistance: item.avgDistance ?? item.avg_distance ?? 0,
        avgDamage: item.avgDamage ?? item.avg_damage ?? 0
      }))
    : [];

  // games may be absent if the backend hasn't been redeployed yet — pass
  // through as null so the popup can render placeholder pills gracefully.
  const games = data?.games ?? null;

  return { rows, games };
}

/**
 * Called when a SubscribeToLobby WebSocket message is intercepted.
 * Saves the playerId to local storage only if not already cached —
 * avoids redundant writes on every new game while keeping the value
 * fresh if it somehow changes (e.g. account switch).
 */
export async function cachePlayerId(message) {
  const playerId = message?.payload?.playerId;

  if (!playerId) {
    console.warn("[GeoCatchr] LOBBY_PLAYER_ID received but playerId was missing");
    return {};
  }

  const stored = await chrome.storage.local.get([STORAGE_KEYS.PLAYER_ID]);

  if (stored[STORAGE_KEYS.PLAYER_ID] === playerId) {
    // Already cached — nothing to do.
    return { playerId, cached: false };
  }

  await chrome.storage.local.set({ [STORAGE_KEYS.PLAYER_ID]: playerId });
  console.log("[GeoCatchr] Player ID cached:", playerId);

  return { playerId, cached: true };
}

export async function forwardDuelPayload(message, sender) {
  const accessToken = await getValidAccessToken();

  // Pull the cached player ID so the ingest Lambda can identify which
  // player is ours without relying on hardcoded team colours.
  const stored = await chrome.storage.local.get([STORAGE_KEYS.PLAYER_ID]);
  const geoguessrPlayerId = stored[STORAGE_KEYS.PLAYER_ID] ?? null;

  if (!geoguessrPlayerId) {
    console.warn("[GeoCatchr] Forwarding duel payload without a cached player ID — ingest may fail");
  }

  const body = {
    receivedAt: new Date().toISOString(),
    pageUrl: sender?.tab?.url || null,
    type: message.type,
    payload: message.payload,
    geoguessr_player_id: geoguessrPlayerId
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
