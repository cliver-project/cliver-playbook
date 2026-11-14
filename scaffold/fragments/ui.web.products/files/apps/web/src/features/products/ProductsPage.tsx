import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiErrorMessage } from "cliver-playbook-app-basic";

import { Button, LoadingState, ProductList } from "../../ui";
import { listProducts } from "./api";

export default function ProductsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["products"],
    queryFn: listProducts,
  });

  const filtered =
    data?.filter((product) =>
      `${product.name} ${product.description}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    ) ?? [];

  return (
    <section className="mx-auto flex max-w-5xl flex-col gap-4 p-4 md:p-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("products.title")}</h1>
        <Button asChild>
          <Link to="/products/new">{t("products.create")}</Link>
        </Button>
      </header>

      {isPending ? <LoadingState /> : null}
      {error ? (
        <div className="flex items-center gap-3">
          <p className="text-destructive">{apiErrorMessage(error)}</p>
          <Button onClick={() => void refetch()}>Retry</Button>
        </div>
      ) : null}
      {!isPending && !error ? (
        <ProductList
          products={filtered}
          search={search}
          onSearch={setSearch}
        />
      ) : null}
    </section>
  );
}
