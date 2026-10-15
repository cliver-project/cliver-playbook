import LanguageDetector from "i18next-browser-languagedetector";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en.json";
import zh from "@/locales/zh.json";

/**
 * i18n bootstrap (ADR-0008).
 *
 * - Bundled locales only (en source language, zh shipped by default) — no
 *   network fetch, deterministic startup. More languages = add a JSON file
 *   plus a `resources` entry.
 * - Detection order: persisted choice first (localStorage key "i18nextLng",
 *   managed by the detector), then browser language, falling back to English.
 * - All user-visible strings go through `t()` — components never hardcode
 *   display copy.
 */
void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "zh"],
    interpolation: { escapeValue: false }, // React already escapes output
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
    },
  });

export default i18n;
