import type { TranslationBundle } from "cliver-playbook-app-basic/i18n/createI18n.ts";
import en from "cliver-playbook-app-rag-governance/locales/en.json";
import zh from "cliver-playbook-app-rag-governance/locales/zh.json";

/**
 * This package's translations, in the shape `createI18n()` expects.
 *
 * Only the keys this package owns live here: the whole `gov` tree plus its
 * own `nav.*` entries. The deep merge lets every package contribute to one
 * `nav` tree without knowing about the others.
 */
export const govTranslations: TranslationBundle = { en, zh };
