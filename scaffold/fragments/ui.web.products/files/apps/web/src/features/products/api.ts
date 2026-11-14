import { api } from "cliver-playbook-app-basic";

export interface Product {
  id: number;
  name: string;
  description: string;
  price_cents: number;
  created_at: string;
  updated_at: string;
}

export interface ProductCreate {
  name: string;
  description: string;
  price_cents: number;
}

export type ProductUpdate = Partial<ProductCreate>;

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
