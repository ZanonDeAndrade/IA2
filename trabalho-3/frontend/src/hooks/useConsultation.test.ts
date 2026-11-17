import { describe, expect, it } from "vitest";
import { DEFAULT_QUESTION, validateConsultation } from "./useConsultation";

describe("validateConsultation", () => {
  it("normaliza espaços e remove ingredientes repetidos", () => {
    const { input, errors } = validateConsultation("  O que   faço?  ", [" Ovo ", "ovo", "queijo", ""]);
    expect(errors).toEqual([]);
    expect(input).toEqual({ question: "O que faço?", available_ingredients: ["Ovo", "queijo"] });
  });

  it("omite available_ingredients quando não há ingredientes", () => {
    expect(validateConsultation("Receita de bolo?", []).input).toEqual({ question: "Receita de bolo?" });
  });

  it("consulta só com ingredientes usa a pergunta padrão; sem nada, pede um dos dois", () => {
    expect(validateConsultation("  ", ["ovo"]).input).toEqual({ question: DEFAULT_QUESTION, available_ingredients: ["ovo"] });
    expect(validateConsultation("", []).errors).toEqual(["Informe ingredientes ou escreva uma pergunta."]);
  });

  it("aplica os limites do contrato", () => {
    expect(validateConsultation("oi", []).errors).toHaveLength(1);
    expect(validateConsultation("a".repeat(501), []).errors).toHaveLength(1);
    const many = Array.from({ length: 31 }, (_, i) => `item ${i}`);
    expect(validateConsultation("Receita?", many).errors).toEqual(["Informe no máximo 30 ingredientes."]);
    expect(validateConsultation("Receita?", ["x".repeat(81)]).errors).toHaveLength(1);
  });
});
