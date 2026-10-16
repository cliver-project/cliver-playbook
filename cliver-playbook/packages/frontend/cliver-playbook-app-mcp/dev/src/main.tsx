import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createI18n } from "cliver-playbook-app-basic";
// The app's Tailwind entry: it pulls in the packages' stylesheet and names
// their source roots. Imported once, before rendering.
import "./index.css";
import { installAuthClient, userTranslations } from "cliver-playbook-app-user";
import { mcpTranslations } from "cliver-playbook-app-mcp";

import App from "./App";

// Order matters for exactly two things: the axios interceptors are global, so
// they are installed before the first request can be made; and i18next must be
// initialised before the first component renders. A composed app passes every
// additional package's translations here.
installAuthClient();
createI18n(userTranslations, mcpTranslations);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
