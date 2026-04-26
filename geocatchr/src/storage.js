import { STORAGE_KEYS } from "./constants.js";

export async function getAccessToken() {
  const data = await chrome.storage.local.get([STORAGE_KEYS.ACCESS_TOKEN]);
  const accessToken = data[STORAGE_KEYS.ACCESS_TOKEN];

  if (!accessToken) {
    throw new Error("Not signed in");
  }

  return accessToken;
}