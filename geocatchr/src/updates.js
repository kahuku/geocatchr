import { CONFIG } from "./config.js";
import { STORAGE_KEYS } from "./constants.js";

function compareVersions(a, b) {
  const aParts = String(a).trim().split(".").map(Number);
  const bParts = String(b).trim().split(".").map(Number);
  const length = Math.max(aParts.length, bParts.length);

  for (let i = 0; i < length; i++) {
    const aNum = aParts[i] || 0;
    const bNum = bParts[i] || 0;

    if (aNum > bNum) return 1;
    if (aNum < bNum) return -1;
  }

  return 0;
}

export async function checkForExtensionUpdate() {
  const currentVersion = chrome.runtime.getManifest().version;

  try {
    const response = await fetch(`${CONFIG.updates.versionUrl}?t=${Date.now()}`, {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`Version check failed with status ${response.status}`);
    }

    const latestVersion = (await response.text()).trim();

    const updateStatus = {
      checkedAt: new Date().toISOString(),
      currentVersion,
      latestVersion,
      updateAvailable: compareVersions(latestVersion, currentVersion) > 0,
      downloadUrl: CONFIG.updates.downloadUrl,
      error: null
    };

    await chrome.storage.local.set({
      [STORAGE_KEYS.UPDATE_STATUS]: updateStatus
    });

    return { updateStatus };
  } catch (error) {
    const updateStatus = {
      checkedAt: new Date().toISOString(),
      currentVersion,
      latestVersion: null,
      updateAvailable: false,
      downloadUrl: CONFIG.updates.downloadUrl,
      error: String(error.message || error)
    };

    await chrome.storage.local.set({
      [STORAGE_KEYS.UPDATE_STATUS]: updateStatus
    });

    return { updateStatus };
  }
}

async function ensureUpdateAlarm() {
  const alarm = await chrome.alarms.get(CONFIG.updates.alarmName);

  if (!alarm) {
    await chrome.alarms.create(CONFIG.updates.alarmName, {
      delayInMinutes: 1,
      periodInMinutes: CONFIG.updates.intervalMinutes
    });
  }
}

export async function initializeUpdateChecks() {
  await ensureUpdateAlarm();
  await checkForExtensionUpdate();
}

chrome.runtime.onStartup.addListener(initializeUpdateChecks);
chrome.runtime.onInstalled.addListener(initializeUpdateChecks);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === CONFIG.updates.alarmName) {
    checkForExtensionUpdate();
  }
});