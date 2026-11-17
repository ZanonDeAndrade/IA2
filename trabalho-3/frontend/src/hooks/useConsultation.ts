import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, postConsultation } from "../services/api";
import { LIMITS, type ConsultationInput, type ConsultationOutput } from "../types/api";

/**
 * Estados de docs/08-application/frontend.md: idle, validating (erro local), loading, success, empty
 * (INSUFFICIENT), blocked (BLOCKED), error (ERROR do backend ou falha de rede). `retrying` marca o reenvio
 * explícito da mesma consulta. Nada é persistido no navegador.
 */
export type ConsultationPhase = "idle" | "validating" | "loading" | "success" | "empty" | "blocked" | "error";

export interface ConsultationState {
  phase: ConsultationPhase;
  result: ConsultationOutput | null;
  /** Mensagem de falha sem resposta do backend (rede, tempo esgotado, formato inesperado). */
  failure: string | null;
  validationErrors: string[];
  retrying: boolean;
}

/** Margem acima do INFERENCE_TIMEOUT padrão do backend (300 s): o prazo oficial é o do servidor. */
export const CLIENT_TIMEOUT_MS = 330_000;

const INITIAL: ConsultationState = { phase: "idle", result: null, failure: null, validationErrors: [], retrying: false };

const PHASE_BY_STATUS = {
  FOUND: "success",
  INSUFFICIENT: "empty",
  BLOCKED: "blocked",
  ERROR: "error",
} as const satisfies Record<ConsultationOutput["status"], ConsultationPhase>;

/** Pergunta enviada quando o usuário informa apenas ingredientes. */
export const DEFAULT_QUESTION = "O que posso preparar com estes ingredientes?";

export interface ValidationResult {
  input: ConsultationInput | null;
  errors: string[];
}

/** Validação local espelhando os limites do contrato; remove espaços extras e ingredientes repetidos. */
export function validateConsultation(question: string, ingredients: string[]): ValidationResult {
  const errors: string[] = [];
  let q = question.trim().replace(/\s+/g, " ");
  const hasIngredients = ingredients.some((i) => i.trim());
  if (!q && hasIngredients) {
    q = DEFAULT_QUESTION; // consulta só com ingredientes: o contrato exige `question`
  }
  if (!q) {
    errors.push("Informe ingredientes ou escreva uma pergunta.");
  } else if (q.length < LIMITS.questionMin) {
    errors.push(`Escreva uma pergunta com pelo menos ${LIMITS.questionMin} caracteres.`);
  } else if (q.length > LIMITS.questionMax) {
    errors.push(`A pergunta pode ter no máximo ${LIMITS.questionMax} caracteres.`);
  }
  const seen = new Set<string>();
  const items: string[] = [];
  for (const raw of ingredients) {
    const item = raw.trim().replace(/\s+/g, " ");
    const key = item.toLocaleLowerCase("pt-BR");
    if (!item || seen.has(key)) continue;
    seen.add(key);
    items.push(item);
  }
  if (items.length > LIMITS.ingredientsMax) {
    errors.push(`Informe no máximo ${LIMITS.ingredientsMax} ingredientes.`);
  }
  if (items.some((i) => i.length > LIMITS.ingredientMaxChars)) {
    errors.push(`Cada ingrediente pode ter no máximo ${LIMITS.ingredientMaxChars} caracteres.`);
  }
  if (errors.length) return { input: null, errors };
  return { input: items.length ? { question: q, available_ingredients: items } : { question: q }, errors };
}

export function useConsultation() {
  const [state, setState] = useState<ConsultationState>(INITIAL);
  const controllerRef = useRef<AbortController | null>(null);
  const lastInputRef = useRef<ConsultationInput | null>(null);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    },
    [],
  );

  const run = useCallback(async (input: ConsultationInput, retrying: boolean) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    lastInputRef.current = input;
    const timer = setTimeout(
      () => controller.abort(new ApiError("timeout", "A consulta demorou mais que o esperado. Tente novamente.")),
      CLIENT_TIMEOUT_MS,
    );
    setState((prev) => ({ ...prev, phase: "loading", failure: null, validationErrors: [], retrying }));
    try {
      const result = await postConsultation(input, { signal: controller.signal });
      if (controllerRef.current !== controller) return; // consulta substituída ou componente desmontado
      setState({ phase: PHASE_BY_STATUS[result.status], result, failure: null, validationErrors: [], retrying: false });
    } catch (err) {
      if (controllerRef.current !== controller) return;
      if (err instanceof ApiError && err.kind === "aborted") return;
      const message = err instanceof ApiError ? err.message : "Erro inesperado ao enviar a consulta.";
      setState({ phase: "error", result: null, failure: message, validationErrors: [], retrying: false });
    } finally {
      clearTimeout(timer);
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, []);

  const submit = useCallback(
    (question: string, ingredients: string[]) => {
      const { input, errors } = validateConsultation(question, ingredients);
      if (!input) {
        setState((prev) => ({ ...prev, phase: "validating", validationErrors: errors, retrying: false }));
        return;
      }
      void run(input, false);
    },
    [run],
  );

  const retry = useCallback(() => {
    if (lastInputRef.current) void run(lastInputRef.current, true);
  }, [run]);

  return { state, submit, retry };
}
