import { Check, Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** Languages offered by the bundled locales (see src/i18n/index.ts). */
const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "zh", label: "中文" },
] as const;

/** Header control: switches the UI language; persisted by the i18n detector. */
export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("language.label")}>
          <Languages className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {LANGUAGES.map(({ code, label }) => {
          const current = i18n.language?.startsWith(code);
          return (
            <DropdownMenuItem key={code} onClick={() => void i18n.changeLanguage(code)}>
              <span className="flex items-center gap-2">
                <Check className={`size-4 ${current ? "opacity-100" : "opacity-0"}`} />
                {label}
              </span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
