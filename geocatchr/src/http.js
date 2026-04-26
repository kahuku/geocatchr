export async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();

  let data = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // Response was not JSON.
  }

  if (!response.ok) {
    throw new Error(data?.error || text || `Request failed with status ${response.status}`);
  }

  return data;
}