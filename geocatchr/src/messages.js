import { MESSAGE_TYPES } from "./constants.js";
import { fetchSummary, forwardDuelPayload, cachePlayerId } from "./api.js";
import { login, logout } from "./auth.js";
import { checkForExtensionUpdate } from "./updates.js";

function respondAsync(sendResponse, handler) {
  handler()
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => {
      console.error("[Message Handler] Request failed:", error);

      sendResponse({
        ok: false,
        error: String(error.message || error)
      });
    });

  return true;
}

export function registerMessageHandlers() {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message?.type) {
      case MESSAGE_TYPES.FETCH_SUMMARY:
        return respondAsync(sendResponse, fetchSummary);

      case MESSAGE_TYPES.DUEL_FINISHED:
      case MESSAGE_TYPES.DUEL_FINISHED_RAW:
        return respondAsync(sendResponse, () => forwardDuelPayload(message, sender));

      case MESSAGE_TYPES.LOBBY_PLAYER_ID:
        return respondAsync(sendResponse, () => cachePlayerId(message));

      case MESSAGE_TYPES.LOGIN:
        return respondAsync(sendResponse, login);

      case MESSAGE_TYPES.LOGOUT:
        return respondAsync(sendResponse, logout);

      case MESSAGE_TYPES.CHECK_FOR_UPDATE:
        return respondAsync(sendResponse, checkForExtensionUpdate);

      default:
        return false;
    }
  });
}
