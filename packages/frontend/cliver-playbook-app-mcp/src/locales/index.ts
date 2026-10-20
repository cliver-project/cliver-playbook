import type { TranslationBundle } from "cliver-playbook-app-basic/i18n/createI18n.ts";
import en from "cliver-playbook-app-mcp/locales/en.json";
import zh from "cliver-playbook-app-mcp/locales/zh.json";

/**
 * This package's translations, in the shape `createI18n()` expects:
 *
 *     import { createI18n } from "cliver-playbook-app-basic";
 *     import { userTranslations } from "cliver-playbook-app-user";
 *     import { mcpTranslations } from "cliver-playbook-app-mcp";
 *     createI18n(userTranslations, mcpTranslations);
 *
 * Only the keys this package owns live here: the whole `mcp` tree plus its own
 * `nav.*` entries. The deep merge is what lets three packages contribute to one
 * `nav` tree without any of them knowing about the others.
 *
 * Adding a language = dropping another JSON file next to these two and listing
 * it here; `supportedLngs` is derived from the merged bundles, so nothing else
 * needs to know about it.
 */
export const mcpTranslations: TranslationBundle = { en, zh };
