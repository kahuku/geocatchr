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

  // ---------------------------------------------------------------------
  // Detect the daily shop-claim request so we can capture what's needed
  // to replay it later. Cookies aren't readable here (many are httpOnly);
  // the service worker fetches those separately via chrome.cookies.
  // ---------------------------------------------------------------------

  const originalFetch = window.fetch.bind(window);

  function normalizeHeaders(input, init) {
    const source = init?.headers ?? (input instanceof Request ? input.headers : null);
    if (!source) return {};

    if (source instanceof Headers) {
      return Object.fromEntries(source.entries());
    }

    if (Array.isArray(source)) {
      return Object.fromEntries(source);
    }

    return { ...source };
  }

  async function captureNavigatorInfo() {
    const info = {
      userAgent: navigator.userAgent,
      language: navigator.language,
      languages: navigator.languages
    };

    if (navigator.userAgentData?.getHighEntropyValues) {
      try {
        info.userAgentData = await navigator.userAgentData.getHighEntropyValues([
          "brands",
          "mobile",
          "platform",
          "platformVersion",
          "architecture",
          "bitness",
          "model",
          "fullVersionList"
        ]);
      } catch {
        // Best effort — not all contexts support high-entropy values.
      }
    }

    return info;
  }

  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input?.url;
    const requestHeaders = normalizeHeaders(input, init);

    const response = await originalFetch(input, init);

    if (url?.includes("/api/v4/webshop/daily-shop-claim") && response.ok) {
      // Fire-and-forget: don't delay the page's own handling of the response.
      captureNavigatorInfo()
        .then((navigatorInfo) => {
          window.postMessage(
            {
              source: "geoguessr-duel-tracker",
              type: "DAILY_SHOP_CLAIMED",
              payload: {
                capturedAt: new Date().toISOString(),
                pageUrl: location.href,
                referrer: document.referrer,
                requestHeaders,
                navigatorInfo
              }
            },
            "*"
          );
        })
        .catch(() => {});
    }

    return response;
  };

  console.log("[GeoGuessr Tracker] MAIN world fetch hook installed");
})();
