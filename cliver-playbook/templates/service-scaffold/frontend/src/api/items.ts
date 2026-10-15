import { api } from "./client";

/**
 * Item API — the reference shape for entity API modules: one interface for
 * the row type, one for each request payload, thin typed wrappers over the
 * shared axios client. No state, no caching (TanStack Query owns that at the
 * call sites); mirrors backend/app/schemas/item.py exactly.
 */

export interface Item {
  id: number;
  name: string;
  description: string;
  quantity: number;
  created_at: string;
  updated_at: string;
}

export interface ItemCreateInput {
  name: string;
  description?: string;
  quantity?: number;
}

export interface ItemUpdateInput {
  name?: string;
  description?: string;
  quantity?: number;
}

export async function listItems(): Promise<Item[]> {
  const { data } = await api.get<Item[]>("/items");
  return data;
}

export async function createItem(input: ItemCreateInput): Promise<Item> {
  const { data } = await api.post<Item>("/items", input);
  return data;
}

export async function updateItem(id: number, input: ItemUpdateInput): Promise<Item> {
  const { data } = await api.patch<Item>(`/items/${id}`, input);
  return data;
}

export async function deleteItem(id: number): Promise<void> {
  await api.delete(`/items/${id}`);
}
