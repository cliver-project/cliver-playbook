import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { apiErrorMessage } from "cliver-playbook-app-basic";

import { Button, ErrorState, LoadingState } from "../../ui";
import { deleteProduct, getProduct } from "./api";

export default function ProductDetailPage() {
  const { t } = useTranslation();
  const { productId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const id = Number(productId);
  const { data, isPending, error } = useQuery({
    queryKey: ["products", id],
    queryFn: () => getProduct(id),
  });
  const remove = useMutation({
    mutationFn: () => deleteProduct(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      navigate("/products");
    },
  });

  if (isPending) return <LoadingState />;
  if (error || !data) {
    return <ErrorState message={apiErrorMessage(error)} />;
  }

  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-4 p-4 md:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{data.name}</h1>
        <div className="flex gap-2">
          <Button asChild variant="outline">
            <Link to={`/products/${data.id}/edit`}>{t("products.edit")}</Link>
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(t("products.confirmDelete"))) {
                remove.mutate();
              }
            }}
          >
            {t("products.delete")}
          </Button>
        </div>
      </div>
      <p className="whitespace-pre-wrap text-muted-foreground">
        {data.description}
      </p>
      <p className="text-lg font-medium">
        {(data.price_cents / 100).toFixed(2)}
      </p>
      {remove.error ? (
        <p className="text-destructive">{apiErrorMessage(remove.error)}</p>
      ) : null}
    </section>
  );
}
