import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiErrorMessage } from "cliver-playbook-app-basic";

import { ProductEditor, type ProductForm } from "../../ui";
import {
  createProduct,
  getProduct,
  updateProduct,
  type ProductCreate,
} from "./api";

const EMPTY: ProductCreate = { name: "", description: "", price_cents: 0 };

export default function ProductEditPage() {
  const { productId } = useParams();
  const isEdit = Boolean(productId);
  const id = Number(productId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ProductForm>(EMPTY);

  const existing = useQuery({
    queryKey: ["products", id],
    queryFn: () => getProduct(id),
    enabled: isEdit,
  });

  useEffect(() => {
    if (existing.data) {
      setForm({
        name: existing.data.name,
        description: existing.data.description,
        price_cents: existing.data.price_cents,
      });
    }
  }, [existing.data]);

  const save = useMutation({
    mutationFn: () =>
      isEdit ? updateProduct(id, form) : createProduct(form),
    onSuccess: async (product) => {
      await queryClient.invalidateQueries({ queryKey: ["products"] });
      navigate(`/products/${product.id}`);
    },
  });

  return (
    <section className="mx-auto flex max-w-2xl flex-col gap-4 p-4 md:p-8">
      <ProductEditor
        isEdit={isEdit}
        form={form}
        onChange={setForm}
        onSave={() => save.mutate()}
        onCancel={() => navigate(-1)}
        busy={save.isPending}
        error={save.error ? apiErrorMessage(save.error) : null}
      />
    </section>
  );
}
