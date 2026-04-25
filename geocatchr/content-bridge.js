window.addEventListener("message", (event) => {
  if (event.source !== window) return;

  const data = event.data;
  if (!data || data.source !== "geoguessr-duel-tracker") return;

  chrome.runtime.sendMessage({
    type: data.type,
    payload: data.payload
  });
});