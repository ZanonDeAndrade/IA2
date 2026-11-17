import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, output } from "../test/factories";
import { ApiError, apiBaseUrl, postConsultation } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("postConsultation", () => {
  it("envia o contrato em JSON para /api/v1/consultations", async () => {
    const fetchMock = mockFetch(jsonResponse(output()));
    const out = await postConsultation({ question: "ovos?", available_ingredients: ["ovo"] }, { baseUrl: "http://api.local" });
    expect(out.status).toBe("FOUND");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.local/api/v1/consultations");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ question: "ovos?", available_ingredients: ["ovo"] });
  });

  it.each([
    [422, "BLOCKED", "PROMPT_INJECTION"],
    [503, "ERROR", "LLM_UNAVAILABLE"],
    [504, "ERROR", "UPSTREAM_TIMEOUT"],
  ] as const)("devolve o corpo do contrato mesmo com HTTP %i", async (http, status, code) => {
    mockFetch(jsonResponse(output({ status, recipes: [], sources: [], error: { code, message: "msg" } }), http));
    const out = await postConsultation({ question: "ovos?" });
    expect(out.status).toBe(status);
    expect(out.error?.code).toBe(code);
  });

  it("falha de rede vira ApiError network", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    await expect(postConsultation({ question: "ovos?" })).rejects.toMatchObject({ kind: "network" });
  });

  it("corpo fora do contrato vira ApiError invalid_response", async () => {
    mockFetch(jsonResponse({ detail: "Not Found" }, 404));
    await expect(postConsultation({ question: "ovos?" })).rejects.toMatchObject({ kind: "invalid_response", httpStatus: 404 });
    mockFetch(new Response("<html>", { status: 502 }));
    await expect(postConsultation({ question: "ovos?" })).rejects.toBeInstanceOf(ApiError);
  });

  it("cancelamento e tempo esgotado são distinguidos", async () => {
    const aborted = new AbortController();
    aborted.abort();
    mockFetch(new DOMException("aborted", "AbortError"));
    await expect(postConsultation({ question: "ovos?" }, { signal: aborted.signal })).rejects.toMatchObject({ kind: "aborted" });

    const timed = new AbortController();
    timed.abort(new ApiError("timeout", "demorou"));
    mockFetch(new DOMException("aborted", "AbortError"));
    await expect(postConsultation({ question: "ovos?" }, { signal: timed.signal })).rejects.toMatchObject({ kind: "timeout" });
  });

  it("URL base vem de VITE_API_BASE_URL, sem barra final", () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://backend.local:9000/");
    expect(apiBaseUrl()).toBe("http://backend.local:9000");
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(apiBaseUrl()).toBe("http://localhost:8000");
  });
});
