/**
 * Public surface of the basic frontend package.
 *
 * Two import styles are supported and both are used in the wild:
 *
 * - the barrel (`cliver-playbook-app-basic`) for the handful of things an app
 *   wires up once — client, providers, layout, routes;
 * - deep paths (`cliver-playbook-app-basic/components/ui/button.tsx`) for
 *   everything else, which keeps a component's dependencies explicit and lets
 *   the bundler drop what is not imported.
 *
 * Deep paths carry the source extension. The package's `exports` patterns are
 * matched exactly — `…/components/ui/button` would not resolve, `…/button.tsx`
 * does — which is what makes one package resolvable from another with no
 * aliases configured in the consuming app.
 *
 * Nothing here renders or mutates global state at import time: `createI18n()`
 * and the providers are called by the app, in the app's own order.
 */

export { api, apiErrorMessage, setAuthTokenGetter } from "cliver-playbook-app-basic/api/client.ts";
export { Toaster } from "cliver-playbook-app-basic/components/ui/sonner.tsx";
export { basicTranslations, createI18n } from "cliver-playbook-app-basic/i18n/createI18n.ts";
export {
  AppLayout,
  basicNavItems,
  type AppLayoutProps,
  type NavItem,
} from "cliver-playbook-app-basic/layout/AppLayout.tsx";
export { queryClient } from "cliver-playbook-app-basic/lib/queryClient.ts";
export { cn } from "cliver-playbook-app-basic/lib/utils.ts";
export { basicRoutes } from "cliver-playbook-app-basic/routes.tsx";
export {
  ThemeProvider,
  useTheme,
  type ResolvedTheme,
  type ThemeMode,
} from "cliver-playbook-app-basic/theme/ThemeProvider.tsx";
