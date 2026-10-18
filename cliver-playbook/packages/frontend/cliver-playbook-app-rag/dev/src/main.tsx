import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createI18n } from "cliver-playbook-app-basic";
// The app's Tailwind entry: it pulls in the packages' stylesheet and names
// their source roots. Imported once, before rendering.
import "./index.css";
import { ragTranslations } from "cliver-playbook-app-rag";
import { installAuthClient, userTranslations } from "cliver-playbook-app-user";

import App from "./App";

// The axios interceptors are global: install them before the first request.
// i18next must be initialised before the first component renders. A composed
// app passes every additional package's translations here.
installAuthClient();
createI18n(userTranslations, ragTranslations);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
