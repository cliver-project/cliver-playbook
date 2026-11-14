import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "cliver-playbook-app-basic/components/ui/card.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";

import { EmptyState } from "./feedback";

export type ProductSummary = {
  id: number;
  name: string;
  description: string;
  price_cents: number;
};

export function ProductList({
  products,
  search,
  onSearch,
}: {
  products: ProductSummary[];
  search: string;
  onSearch: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <Input
        aria-label={t("products.search")}
        placeholder={t("products.search")}
        value={search}
        onChange={(event) => onSearch(event.target.value)}
      />
      {products.length === 0 ? (
        <EmptyState title={t("products.empty")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((product) => (
            <Link key={product.id} to={`/products/${product.id}`}>
              <Card className="h-full transition-colors hover:bg-accent">
                <CardHeader>
                  <CardTitle className="text-base">{product.name}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="line-clamp-2 text-sm text-muted-foreground">
                    {product.description}
                  </p>
                  <p className="text-sm font-medium">
                    {(product.price_cents / 100).toFixed(2)}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
