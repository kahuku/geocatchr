export const CONFIG = {
  api: {
    ingestUrl: "https://f53qk2aal4.execute-api.us-east-1.amazonaws.com/ingest-duel",
    summaryUrl: "https://f53qk2aal4.execute-api.us-east-1.amazonaws.com/summary"
  },

  auth: {
    cognitoDomain: "https://us-east-1jhgrfzkpz.auth.us-east-1.amazoncognito.com",
    clientId: "7vmvhj8v6c6cckec9i2hdvrlkc",
    scope: "openid email profile"
  },

  updates: {
    alarmName: "check-extension-update",
    intervalMinutes: 180,
    versionUrl: "https://raw.githubusercontent.com/kahuku/geocatchr/main/version.txt",
    downloadUrl: "https://github.com/kahuku/geocatchr"
  }
};