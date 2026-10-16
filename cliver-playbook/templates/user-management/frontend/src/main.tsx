import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "@/i18n"; // side-effect import: registers i18next before any component renders
import "@/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
