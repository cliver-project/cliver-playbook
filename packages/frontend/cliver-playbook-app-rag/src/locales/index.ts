import type { TranslationBundle } from "cliver-playbook-app-basic/i18n/createI18n.ts";
import en from "cliver-playbook-app-rag/locales/en.json";
import zh from "cliver-playbook-app-rag/locales/zh.json";

/**
 * This package's translations, in the shape `createI18n()` expects:
 *
 *     import { createI18n } from "cliver-playbook-app-basic";
 *     import { userTranslations } from "cliver-playbook-app-user";
 *     import { mcpTranslations } from "cliver-playbook-app-mcp";
 *     import { ragTranslations } from "cliver-playbook-app-rag";
 *     createI18n(userTranslations, mcpTranslations, ragTranslations);
 *
 * Only the keys this package owns live here: the whole `rag` tree plus its own
 * `nav.*` entries. The deep merge lets every package contribute to one `nav`
 * tree without knowing about the others.
 */
export const ragTranslations: TranslationBundle = { en, zh };
