import type { TranslationBundle } from "cliver-playbook-app-basic/i18n/createI18n.ts";
import en from "cliver-playbook-app-user/locales/en.json";
import zh from "cliver-playbook-app-user/locales/zh.json";

/**
 * This package's translations, in the shape `createI18n()` expects::
 *
 *     import { createI18n } from "cliver-playbook-app-basic";
 *     import { userTranslations } from "cliver-playbook-app-user";
 *     createI18n(userTranslations);
 *
 * Only the keys this package owns live here: the `auth`, `admin` and `profile`
 * trees plus its own `nav.*` entries. The app's bundle (`app.title`, `common.*`,
 * `nav.home`, …) stays in the basic package, and the deep merge is what lets
 * both packages contribute to the same `nav` tree.
 *
 * Adding a language = dropping another JSON file next to these two and listing
 * it here; `supportedLngs` is derived from the merged bundles, so nothing else
 * needs to know about it.
 */
export const userTranslations: TranslationBundle = { en, zh };
