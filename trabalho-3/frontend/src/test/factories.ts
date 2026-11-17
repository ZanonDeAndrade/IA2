/**
 * Dados SINTÉTICOS usados só nos testes unitários (mock de fetch). Nunca importar no código da aplicação.
 * A integração real com o backend é verificada contra a API em execução (ver frontend/README.md).
 */
import { vi } from "vitest";
import type { ConsultationOutput, RecipeCard } from "../types/api";

export function recipe(over: Partial<RecipeCard> = {}): RecipeCard {
  return {
    recipe_id: "teste-001-v1",
    document_id: "teste-001",
    title: "[TESTE] Omelete",
    topic_key: "pratos_principais",
    compatibility: "COMPLETE",
    available_ingredients: ["ovo", "queijo"],
    missing_ingredients: [],
    ingredients: [
      { name: "ovos", quantity_text: "2", required: true, notes: null },
      { name: "queijo", quantity_text: null, required: false, notes: "ralado" },
    ],
    instructions: ["Bata os ovos.", "Leve à frigideira."],
    portions: null,
    preparation_time: "10 minutos",
    temperature: null,
    source_url: "https://example.org/teste/omelete",
    source_id: "teste-001",
    ...over,
  };
}

export function output(over: Partial<ConsultationOutput> = {}): ConsultationOutput {
  const r = recipe();
  return {
    request_id: "req0000000000001",
    status: "FOUND",
    answer: "Encontrei uma receita na base.",
    recipes: [r],
    sources: [{ document_id: r.document_id, recipe_id: r.recipe_id, title: r.title, url: r.source_url, license: "CC BY-SA" }],
    error: null,
    ...over,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function mockFetch(...responses: Array<Response | Error | DOMException | (() => Promise<Response>)>) {
  const fn = vi.fn((_url: string, _init?: RequestInit) => {
    const next = responses.shift();
    if (!next) return Promise.reject(new Error("sem resposta roteirizada"));
    if (next instanceof Response) return Promise.resolve(next);
    return typeof next === "function" ? next() : Promise.reject(next);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
