import { STORAGE_KEYS } from "./constants.js";
import { refreshAccessToken } from "./auth.js";

export async function getAccessToken() {
  const data = await chrome.storage.local.get([STORAGE_KEYS.ACCESS_TOKEN]);
  const accessToken = data[STORAGE_KEYS.ACCESS_TOKEN];

  if (!accessToken) {
    throw new Error("Not signed in");
  }

  return accessToken;
}

export async function getValidAccessToken() {
  const data = await chrome.storage.local.get([
    "access_token",
    "refresh_token",
    "expires_at"
  ]);

  const { access_token, refresh_token, expires_at } = data;

  if (!refresh_token) {
    throw new Error("Not signed in");
  }

  const bufferMs = 60 * 1000;

  const isValid =
    access_token &&
    expires_at &&
    Date.now() < expires_at - bufferMs;

  if (isValid) {
    return access_token;
  }

  console.log("[Auth] Access token expired, refreshing...");

  return refreshAccessToken(refresh_token);
}