const ENDPOINT_URL = "https://f53qk2aal4.execute-api.us-east-1.amazonaws.com/ingest-duel";
const SUMMARY_ENDPOINT_URL = "https://f53qk2aal4.execute-api.us-east-1.amazonaws.com/summary";

async function fetchSummaryFromApi() {
  const { access_token } = await chrome.storage.local.get(["access_token"]);

  if (!access_token) {
    throw new Error("Not signed in");
  }

  const response = await fetch(SUMMARY_ENDPOINT_URL, {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${access_token}`
    }
  });

  const text = await response.text();
  let data = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch (err) {
    console.warn("[Summary] Failed to parse JSON response:", err);
  }

  if (!response.ok) {
    throw new Error(data?.error || text || `Summary request failed with status ${response.status}`);
  }

  return data;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "FETCH_SUMMARY") {
    (async () => {
      try {
        const data = await fetchSummaryFromApi();

        // Normalize whatever shape your future API returns
        // into the popup shape we want now.
        const rows = Array.isArray(data?.countries)
          ? data.countries.map((item) => ({
              country: item.country,
              totalRounds: item.totalRounds ?? item.rounds_played ?? 0,
              avgDistance: item.avgDistance ?? item.avg_distance ?? 0,
              avgDamage: item.avgDamage ?? item.avg_damage ?? 0
            }))
          : [];

        sendResponse({
          ok: true,
          rows
        });
      } catch (error) {
        console.error("[Summary] Fetch failed:", error);
        sendResponse({
          ok: false,
          error: String(error.message || error)
        });
      }
    })();

    return true;
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || (message.type !== "DUEL_FINISHED" && message.type !== "DUEL_FINISHED_RAW")) {
    return;
  }

  (async () => {
    try {
      const body = {
        receivedAt: new Date().toISOString(),
        pageUrl: sender?.tab?.url || null,
        type: message.type,
        payload: message.payload
      };

      const { access_token } = await chrome.storage.local.get(["access_token"]);
      console.log("Access token: ", access_token);

      const response = await fetch(ENDPOINT_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${access_token}`
        },
        body: JSON.stringify(body)
      });

      const text = await response.text().catch(() => "");

      console.log("[GeoGuessr Tracker] Forwarded successfully:", response.status, text);

      sendResponse({
        ok: true,
        status: response.status,
        responseText: text
      });

    } catch (error) {
      console.error("[GeoGuessr Tracker] Forwarding failed:", error);

      sendResponse({
        ok: false,
        error: String(error)
      });
    }
  })();

  return true; // keeps sendResponse alive for async
});


const COGNITO_DOMAIN = "https://us-east-1jhgrfzkpz.auth.us-east-1.amazoncognito.com";
const CLIENT_ID = "7vmvhj8v6c6cckec9i2hdvrlkc";

function base64UrlEncode(arrayBuffer) {
  const bytes = new Uint8Array(arrayBuffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256(plainText) {
  const encoder = new TextEncoder();
  const data = encoder.encode(plainText);
  return crypto.subtle.digest("SHA-256", data);
}

function randomString(length = 64) {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, x => chars[x % chars.length]).join("");
}

async function signInWithCognito() {
  const redirectUri = chrome.identity.getRedirectURL();
  const codeVerifier = randomString(64);
  const codeChallenge = base64UrlEncode(await sha256(codeVerifier));
  const state = randomString(32);

  await chrome.storage.local.set({ pkce_code_verifier: codeVerifier, oauth_state: state });

const authUrl =
  `${COGNITO_DOMAIN}/oauth2/authorize` +
  `?response_type=code` +
  `&client_id=${encodeURIComponent(CLIENT_ID)}` +
  `&redirect_uri=${encodeURIComponent(redirectUri)}` +
  `&scope=${encodeURIComponent("openid email profile")}` +
  `&state=${encodeURIComponent(state)}` +
  `&prompt=${encodeURIComponent("login")}` +
  `&code_challenge_method=S256` +
  `&code_challenge=${encodeURIComponent(codeChallenge)}`;


  console.log("[Auth] redirectUri exact:", JSON.stringify(redirectUri));
  console.log("[Auth] authUrl exact:", authUrl);
  console.log("[Auth] About to launch auth flow");
console.log("[Auth] Full auth URL:", authUrl);

  const responseUrl = await chrome.identity.launchWebAuthFlow({
    url: authUrl,
    interactive: true
  });

  if (!responseUrl) {
    throw new Error("No redirect URL returned from login flow");
  }

  const url = new URL(responseUrl);
  const returnedState = url.searchParams.get("state");
  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");

  if (error) {
    throw new Error(`OAuth error: ${error}`);
  }

  const saved = await chrome.storage.local.get(["pkce_code_verifier", "oauth_state"]);
  if (returnedState !== saved.oauth_state) {
    throw new Error("OAuth state mismatch");
  }
  if (!code) {
    throw new Error("No authorization code returned");
  }

  return { code, codeVerifier: saved.pkce_code_verifier, redirectUri };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
if (message?.type === "LOGIN") {
  console.log("[Auth] LOGIN message received");

  signInWithCognito()
    .then(async (result) => {
      console.log("[Auth] Authorization code received:", result);

      const tokens = await exchangeCodeForTokens(result);
      console.log("[Auth] Tokens received:", tokens);

      await chrome.storage.local.set({
        id_token: tokens.id_token,
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
        token_type: tokens.token_type,
        expires_in: tokens.expires_in
      });

      sendResponse({ ok: true, result: tokens });
    })
    .catch((error) => {
      console.error("[Auth] Login failed:", error);
      sendResponse({ ok: false, error: error.message, stack: error.stack });
      console.error("[Auth] launchWebAuthFlow failed:", error);
    });

  return true;
}
  if (message?.type === "LOGOUT") {
    console.log("[Auth] LOGOUT message received");

    signOutFromCognito()
      .then(() => {
        sendResponse({ ok: true });
      })
      .catch((error) => {
        console.error("[Auth] Logout failed:", error);
        sendResponse({ ok: false, error: error.message, stack: error.stack });
      });

    return true;
  }
});


async function exchangeCodeForTokens({ code, codeVerifier, redirectUri }) {
  console.log("[Auth] exchangeCodeForTokens started");

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code,
    redirect_uri: redirectUri,
    code_verifier: codeVerifier
  });

  const tokenUrl = `${COGNITO_DOMAIN}/oauth2/token`;
  console.log("[Auth] tokenUrl:", tokenUrl);
  console.log("[Auth] token request body:", body.toString());

  const response = await fetch(tokenUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: body.toString()
  });

  const text = await response.text();
  console.log("[Auth] token response status:", response.status);
  console.log("[Auth] token response raw text:", text);

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`Token endpoint did not return JSON: ${text}`);
  }

  if (!response.ok) {
    throw new Error(data.error_description || data.error || "Token exchange failed");
  }

  console.log("[Auth] token exchange success");
  return data;
}

async function signOutFromCognito() {
  console.log("[Auth] signOutFromCognito started");

  const redirectUri = chrome.identity.getRedirectURL();
  const logoutUrl =
    `${COGNITO_DOMAIN}/logout` +
    `?client_id=${encodeURIComponent(CLIENT_ID)}` +
    `&logout_uri=${encodeURIComponent(redirectUri)}`;

  console.log("[Auth] logoutUrl:", logoutUrl);

  try {
    await chrome.identity.launchWebAuthFlow({
      url: logoutUrl,
      interactive: true
    });
  } catch (err) {
    console.warn("[Auth] Hosted logout flow had an issue, continuing local logout:", err);
  }

  await chrome.storage.local.remove([
    "id_token",
    "access_token",
    "refresh_token",
    "token_type",
    "expires_in",
    "pkce_code_verifier",
    "oauth_state"
  ]);

  console.log("[Auth] Local tokens cleared");
}