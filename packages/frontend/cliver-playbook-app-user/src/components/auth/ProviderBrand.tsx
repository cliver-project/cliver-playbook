import { cn } from "cliver-playbook-app-basic/lib/utils.ts";

import type { OAuthProviderButton } from "cliver-playbook-app-user/api/auth.ts";

/** The minimum metadata needed to resolve a provider's display label. */
export interface ProviderLabelSource {
  /** Default label, used when `labels` has no match for the active locale. */
  label: string;
  /** Locale tag (lowercase) -> label override, e.g. { en: "WeChat", zh: "微信" }. */
  labels?: Record<string, string>;
}

/**
 * Resolve a label for the active UI language.
 *
 * The backend returns a default label plus lowercase locale overrides. Try the
 * full tag first ("zh-cn"), then its base ("zh"), then the default — so an app
 * configured for "zh-CN" still finds a "zh" entry.
 */
export function resolveProviderLabel(
  label: string,
  labels: Record<string, string> | undefined,
  language: string,
): string {
  for (const candidate of [language, language.split("-")[0]]) {
    const value = labels?.[candidate.toLowerCase()];
    if (value) return value;
  }
  return label;
}

/** Resolve a provider object's label for the active UI language. */
export function providerLabel(provider: ProviderLabelSource, language: string): string {
  return resolveProviderLabel(provider.label, provider.labels, language);
}

/**
 * Provider brand mark: the configured image when present, otherwise a
 * brand-colored initial badge. Renders nothing when the provider carries no
 * brand metadata, leaving the plain outline button.
 */
export function ProviderIcon({
  provider,
  className,
}: {
  provider: OAuthProviderButton;
  className?: string;
}) {
  if (provider.icon) {
    return (
      <img
        src={provider.icon}
        alt=""
        aria-hidden="true"
        className={cn("size-4 shrink-0 rounded-sm object-contain", className)}
      />
    );
  }
  if (!provider.brand_color) return null;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-4 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-white",
        className,
      )}
      style={{ backgroundColor: provider.brand_color }}
    >
      {(provider.label || provider.key).charAt(0).toUpperCase()}
    </span>
  );
}
