import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { api, apiErrorMessage } from "@/api/client";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface Item {
  id: number;
  name: string;
  description: string;
  quantity: number;
}

/**
 * Landing page doubling as the wiring demo: i18n copy, themed primitives,
 * axios client and TanStack Query all meet here. Real content pages (like
 * /items) take over as the project grows.
 */
export default function HomePage() {
  const { t } = useTranslation();
  const { data, isPending, error } = useQuery({
    queryKey: ["items"],
    queryFn: async () => (await api.get<Item[]>("/items")).data,
  });

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">{t("home.welcome")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("home.description")}</p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t("home.itemsCardTitle")}</CardTitle>
          <CardDescription>{t("home.itemsCardDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {isPending && <p className="text-muted-foreground text-sm">{t("common.loading")}</p>}
          {error && (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircle className="size-4" />
              {t("home.apiDown")} ({apiErrorMessage(error)})
            </p>
          )}
          {data && <p className="text-sm">{t("home.itemsCount", { count: data.length })}</p>}
        </CardContent>
        <CardFooter>
          <Button asChild variant="outline" size="sm">
            <Link to="/items">{t("home.manageItems")}</Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
