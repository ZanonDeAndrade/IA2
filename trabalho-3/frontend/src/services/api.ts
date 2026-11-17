import type { ConsultationInput, ConsultationOutput } from "../types/api";

/**
 * Única camada que fala HTTP com o backend.
 *
 * O backend sempre responde no formato ConsultationOutput, inclusive em 422/502/503/504/500: o `status`
 * semântico (FOUND, INSUFFICIENT, BLOCKED, ERROR) vale mais que o código HTTP. Só viram ApiError as falhas
 * em que não há resposta no contrato (rede, cancelamento, corpo inesperado).
 */

export type ApiErrorKind = "network" | "aborted" | "timeout" | "invalid_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly httpStatus: number | null;

  constructor(kind: ApiErrorKind, message: string, httpStatus: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.httpStatus = httpStatus;
  }
}

const DEFAULT_BASE_URL = "http://localhost:8000";

export function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  return (configured && configured.trim() ? configured.trim() : DEFAULT_BASE_URL).replace(/\/+$/, "");
}

const STATUSES = new Set(["FOUND", "INSUFFICIENT", "BLOCKED", "ERROR"]);

function isConsultationOutput(value: unknown): value is ConsultationOutput {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.request_id === "string" &&
    typeof v.status === "string" &&
    STATUSES.has(v.status) &&
    typeof v.answer === "string" &&
    Array.isArray(v.recipes) &&
    Array.isArray(v.sources)
  );
}

export interface RequestOptions {
  signal?: AbortSignal;
  baseUrl?: string;
}

export async function postConsultation(
  input: ConsultationInput,
  { signal, baseUrl = apiBaseUrl() }: RequestOptions = {},
): Promise<ConsultationOutput> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/v1/consultations`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(input),
      ...(signal ? { signal } : {}),
    });
  } catch {
    if (signal?.aborted) {
      const timedOut = signal.reason instanceof ApiError && signal.reason.kind === "timeout";
      throw timedOut ? signal.reason : new ApiError("aborted", "A consulta foi cancelada.");
    }
    throw new ApiError("network", "Não foi possível conectar ao servidor. Verifique se o backend está em execução.");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("invalid_response", "O servidor respondeu em um formato inesperado.", response.status);
  }
  if (!isConsultationOutput(body)) {
    throw new ApiError("invalid_response", "O servidor respondeu em um formato inesperado.", response.status);
  }
  return { ...body, error: body.error ?? null };
}
