import { initializeUpdateChecks } from "./src/updates.js";
import { registerMessageHandlers } from "./src/messages.js";

registerMessageHandlers();
initializeUpdateChecks();