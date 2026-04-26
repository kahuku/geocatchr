(() => {
  if (window.__geoDuelTrackerInstalled) return;
  window.__geoDuelTrackerInstalled = true;

  const OriginalWebSocket = window.WebSocket;

  function tryParseJson(data) {
    if (typeof data !== "string") return null;

    try {
      return JSON.parse(data);
    } catch {
      return null;
    }
  }

  function containsDuelFinished(value) {
    if (value == null) return false;

    if (typeof value === "string") {
      return value.includes("DuelFinished");
    }

    if (Array.isArray(value)) {
      return value.some(containsDuelFinished);
    }

    if (typeof value === "object") {
      return Object.values(value).some(containsDuelFinished);
    }

    return false;
  }

  function PatchedWebSocket(...args) {
    const ws = new OriginalWebSocket(...args);

    // Intercept incoming messages (server -> client)
    ws.addEventListener("message", (event) => {
      const parsed = tryParseJson(event.data);

      if (parsed && containsDuelFinished(parsed)) {
        window.postMessage(
          {
            source: "geoguessr-duel-tracker",
            type: "DUEL_FINISHED",
            payload: parsed
          },
          "*"
        );
      } else if (typeof event.data === "string" && event.data.includes("DuelFinished")) {
        window.postMessage(
          {
            source: "geoguessr-duel-tracker",
            type: "DUEL_FINISHED_RAW",
            payload: event.data
          },
          "*"
        );
      }
    });

    // Intercept outgoing messages (client -> server) to catch SubscribeToLobby.
    // This is sent by the GeoGuessr client when joining a new duel lobby and
    // contains the authoritative playerId for the current user.
    const originalSend = ws.send.bind(ws);
    ws.send = function (data) {
      const parsed = tryParseJson(data);

      if (parsed?.code === "SubscribeToLobby" && parsed?.playerId) {
        window.postMessage(
          {
            source: "geoguessr-duel-tracker",
            type: "LOBBY_PLAYER_ID",
            payload: {
              playerId: parsed.playerId,
              gameId: parsed.gameId ?? null
            }
          },
          "*"
        );
      }

      return originalSend(data);
    };

    return ws;
  }

  PatchedWebSocket.prototype = OriginalWebSocket.prototype;
  Object.setPrototypeOf(PatchedWebSocket, OriginalWebSocket);
  window.WebSocket = PatchedWebSocket;

  console.log("[GeoGuessr Tracker] MAIN world WebSocket hook installed");
})();
