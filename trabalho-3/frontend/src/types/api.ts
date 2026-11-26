/**
 * Contrato HTTP de POST /api/v1/consultations.
 * Espelho de backend/app/schemas/query.py — manter os dois em sincronia (snake_case, mesmos campos).
 */

export type ConsultationStatus = "FOUND" | "INSUFFICIENT" | "BLOCKED" | "ERROR";

export type ErrorCode =
  | "INPUT_INVALID"
  | "OUT_OF_SCOPE"
  | "PROMPT_INJECTION"
  | "CORPUS_EMPTY"
  | "DOCUMENT_NOT_FOUND"
  | "MCP_UNAVAILABLE"
  | "MCP_TOOL_ERROR"
  | "LLM_UNAVAILABLE"
  | "LLM_PROTOCOL_ERROR"
  | "UPSTREAM_TIMEOUT"
  | "INTERNAL_ERROR";

export type Compatibility = "COMPLETE" | "PARTIAL" | "NO_MATCH" | "NOT_EVALUATED";

export interface ConsultationInput {
  question: string;
  available_ingredients?: string[];
}

export interface IngredientView {
  name: string;
  quantity_text: string | null;
  required: boolean;
  notes: string | null;
}

export interface RecipeCard {
  recipe_id: string;
  document_id: string;
  title: string;
  topic_key: string;
  /** Categoria documentada na fonte (campos opcionais: respostas antigas não os trazem). */
  topic_label?: string | null;
  subcategory?: string | null;
  compatibility: Compatibility;
  available_ingredients: string[];
  missing_ingredients: string[];
  ingredients: IngredientView[];
  instructions: string[];
  portions: string | null;
  preparation_time: string | null;
  temperature: string | null;
  source_url: string;
  source_id: string;
}

export interface SourceRef {
  document_id: string;
  recipe_id: string;
  title: string;
  url: string;
  license: string | null;
}

export interface ErrorInfo {
  code: ErrorCode;
  message: string;
}

export interface ConsultationOutput {
  request_id: string;
  status: ConsultationStatus;
  answer: string;
  recipes: RecipeCard[];
  sources: SourceRef[];
  error: ErrorInfo | null;
}

/** Limites do contrato (ConsultationInput e Settings do backend). O backend continua sendo a fonte de validação. */
export const LIMITS = {
  questionMin: 3,
  questionMax: 500,
  ingredientsMax: 30,
  ingredientMaxChars: 80,
} as const;
