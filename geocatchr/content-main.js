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

    return ws;
  }

  PatchedWebSocket.prototype = OriginalWebSocket.prototype;
  Object.setPrototypeOf(PatchedWebSocket, OriginalWebSocket);
  window.WebSocket = PatchedWebSocket;

  console.log("[GeoGuessr Tracker] MAIN world WebSocket hook installed");
})();