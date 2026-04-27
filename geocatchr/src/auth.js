import { CONFIG } from "./config.js";
import { STORAGE_KEYS } from "./constants.js";
import { fetchJson } from "./http.js";

function base64UrlEncode(arrayBuffer) {
  const bytes = new Uint8Array(arrayBuffer);
  let binary = "";

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function sha256(value) {
  const encoder = new TextEncoder();
  return crypto.subtle.digest("SHA-256", encoder.encode(value));
}

function randomString(length = 64) {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const values = new Uint8Array(length);

  crypto.getRandomValues(values);

  return Array.from(values, (x) => chars[x % chars.length]).join("");
}

async function startCognitoLogin() {
  const redirectUri = chrome.identity.getRedirectURL();
  const codeVerifier = randomString(64);
  const codeChallenge = base64UrlEncode(await sha256(codeVerifier));
  const state = randomString(32);

  await chrome.storage.local.set({
    [STORAGE_KEYS.PKCE_VERIFIER]: codeVerifier,
    [STORAGE_KEYS.OAUTH_STATE]: state
  });

  const authUrl =
    `${CONFIG.auth.cognitoDomain}/oauth2/authorize` +
    `?response_type=code` +
    `&client_id=${encodeURIComponent(CONFIG.auth.clientId)}` +
    `&redirect_uri=${encodeURIComponent(redirectUri)}` +
    `&scope=${encodeURIComponent(CONFIG.auth.scope)}` +
    `&state=${encodeURIComponent(state)}` +
    `&prompt=${encodeURIComponent("login")}` +
    `&code_challenge_method=S256` +
    `&code_challenge=${encodeURIComponent(codeChallenge)}`;

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

  const saved = await chrome.storage.local.get([
    STORAGE_KEYS.PKCE_VERIFIER,
    STORAGE_KEYS.OAUTH_STATE
  ]);

  if (returnedState !== saved[STORAGE_KEYS.OAUTH_STATE]) {
    throw new Error("OAuth state mismatch");
  }

  if (!code) {
    throw new Error("No authorization code returned");
  }

  return {
    code,
    codeVerifier: saved[STORAGE_KEYS.PKCE_VERIFIER],
    redirectUri
  };
}

async function exchangeCodeForTokens({ code, codeVerifier, redirectUri }) {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CONFIG.auth.clientId,
    code,
    redirect_uri: redirectUri,
    code_verifier: codeVerifier
  });

  return fetchJson(`${CONFIG.auth.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: body.toString()
  });
}

export async function login() {
  const authResult = await startCognitoLogin();
  const tokens = await exchangeCodeForTokens(authResult);
  const expiresAt = Date.now() + tokens.expires_in * 1000;

  await chrome.storage.local.set({
    [STORAGE_KEYS.ID_TOKEN]: tokens.id_token,
    [STORAGE_KEYS.ACCESS_TOKEN]: tokens.access_token,
    [STORAGE_KEYS.REFRESH_TOKEN]: tokens.refresh_token,
    [STORAGE_KEYS.TOKEN_TYPE]: tokens.token_type,
    [STORAGE_KEYS.EXPIRES_IN]: tokens.expires_in,
    [STORAGE_KEYS.EXPIRES_AT]: expiresAt
  });

  return { tokens };
}

export async function refreshAccessToken(refreshToken) {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: CONFIG.auth.clientId,
    refresh_token: refreshToken
  });

  const response = await fetch(`${CONFIG.auth.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: body.toString()
  });

  const text = await response.text();

  let tokens;
  try {
    tokens = JSON.parse(text);
  } catch {
    throw new Error("Failed to parse token refresh response");
  }

  if (!response.ok) {
    console.warn("[Auth] Refresh token failed, clearing session");

    await chrome.storage.local.remove([
      "id_token",
      "access_token",
      "refresh_token",
      "token_type",
      "expires_in",
      "expires_at"
    ]);

    throw new Error("Session expired. Please sign in again.");
  }

  const expiresAt = Date.now() + tokens.expires_in * 1000;

  await chrome.storage.local.set({
    id_token: tokens.id_token,
    access_token: tokens.access_token,
    token_type: tokens.token_type,
    expires_in: tokens.expires_in,
    expires_at: expiresAt
  });

  return tokens.access_token;
}

export async function logout() {
  // Keep popup sign-out instant and reliable. Cognito's Hosted UI logout can
  // hang or close without returning inside a Chrome extension popup, so local
  // token cleanup is the source of truth for signing the extension out.
  await chrome.storage.local.remove([
    STORAGE_KEYS.ID_TOKEN,
    STORAGE_KEYS.ACCESS_TOKEN,
    STORAGE_KEYS.REFRESH_TOKEN,
    STORAGE_KEYS.TOKEN_TYPE,
    STORAGE_KEYS.EXPIRES_IN,
    STORAGE_KEYS.EXPIRES_AT,
    STORAGE_KEYS.PKCE_VERIFIER,
    STORAGE_KEYS.OAUTH_STATE,
    STORAGE_KEYS.PLAYER_ID
  ]);

  return {};
}