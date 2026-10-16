import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createI18n } from "cliver-playbook-app-basic";
// The package ships the stylesheet; the app imports it once, before rendering.
import "cliver-playbook-app-basic/styles/index.css";

import App from "./App";

// i18next must be initialised before the first component renders. A composed
// app passes every additional package's translations here.
createI18n();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
