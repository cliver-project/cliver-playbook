import LanguageDetector from "i18next-browser-languagedetector";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "cliver-playbook-app-basic/locales/en.json";
import zh from "cliver-playbook-app-basic/locales/zh.json";

/**
 * i18n bootstrap (ADR-0008).
 *
 * Every package ships its own translations and an app merges them here, so the
 * app owns exactly one i18next instance (a second `init()` would replace the
 * first)::
 *
 *     import { createI18n } from "cliver-playbook-app-basic/i18n/createI18n.ts";
 *     import { userTranslations } from "cliver-playbook-app-user";
 *     createI18n(userTranslations);
 *
 * Merge semantics: per language, deeper keys win (`{items: {title}}` from a
 * later bundle overrides that one key, not the whole `items` tree) — packages
 * therefore only ever add keys they own, and two packages disagreeing about a
 * key is resolved by the order the app passes them.
 *
 * Behaviour otherwise matches the original single-app bootstrap: bundled
 * locales only (no network fetch, deterministic startup), detection order
 * localStorage (key "i18nextLng") then browser language, English fallback, and
 * `t()` for every user-visible string.
 */

/** One language's translation tree: `{en: {items: {title: "…"}}, …}`. */
export type TranslationBundle = Record<string, Record<string, unknown>>;

/** This package's translations — the base every app starts from. */
export const basicTranslations: TranslationBundle = { en, zh };

type Tree = Record<string, unknown>;

function isTree(value: unknown): value is Tree {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Merge `extra` into `base`: nested objects merge, everything else overwrites. */
function mergeTrees(base: Tree, extra: Tree): Tree {
  const merged: Tree = { ...base };
  for (const [key, value] of Object.entries(extra)) {
    const current = merged[key];
    merged[key] = isTree(current) && isTree(value) ? mergeTrees(current, value) : value;
  }
  return merged;
}

function mergeBundles(bundles: readonly TranslationBundle[]): TranslationBundle {
  const merged: TranslationBundle = {};
  for (const bundle of bundles) {
    for (const [language, tree] of Object.entries(bundle)) {
      merged[language] = mergeTrees(merged[language] ?? {}, tree);
    }
  }
  return merged;
}

/**
 * Initialise the singleton i18next instance with this package's translations
 * plus every bundle passed in. Returns the instance (`i18n` is also the
 * default export) — mostly for tests that assert on resolved strings.
 */
export function createI18n(...bundles: readonly TranslationBundle[]) {
  const merged = mergeBundles([basicTranslations, ...bundles]);
  const resources = Object.fromEntries(
    // One namespace on purpose: a translation tree maps to `translation`, so
    // keys stay flat single strings ("items.title") as in the locale files.
    Object.entries(merged).map(([language, tree]) => [language, { translation: tree }]),
  );

  void i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources,
      fallbackLng: "en",
      // Languages are whatever the composed bundles offer — adding a locale
      // file to any package adds the language, no list to keep in sync.
      supportedLngs: Object.keys(merged),
      interpolation: { escapeValue: false }, // React already escapes output
      detection: {
        order: ["localStorage", "navigator"],
        caches: ["localStorage"],
      },
    });

  return i18n;
}

export default i18n;
