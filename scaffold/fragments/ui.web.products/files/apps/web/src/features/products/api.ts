import { api } from "cliver-playbook-app-basic";

import type { components } from "../../contracts/schema";

export type Product = components["schemas"]["Product"];
export type ProductCreate = components["schemas"]["ProductCreate"];
export type ProductUpdate = components["schemas"]["ProductUpdate"];

export async function listProducts(): Promise<Product[]> {
  const response = await api.get<Product[]>("/products");
  return response.data;
}

export async function getProduct(id: number): Promise<Product> {
  const response = await api.get<Product>(`/products/${id}`);
  return response.data;
}

export async function createProduct(payload: ProductCreate): Promise<Product> {
  const response = await api.post<Product>("/products", payload);
  return response.data;
}

export async function updateProduct(
  id: number,
  payload: ProductUpdate,
): Promise<Product> {
  const response = await api.patch<Product>(`/products/${id}`, payload);
  return response.data;
}

export async function deleteProduct(id: number): Promise<void> {
  await api.delete(`/products/${id}`);
}
