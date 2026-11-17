import { describe, expect, it } from "vitest";
import { mergeIngredients, splitIngredients } from "./IngredientInput";

describe("ingredientes", () => {
  it("separa por vírgula, ponto e vírgula e quebra de linha", () => {
    expect(splitIngredients(" ovo, queijo ;tomate\n  ,  ")).toEqual(["ovo", "queijo", "tomate"]);
  });

  it("não repete ingredientes ao juntar", () => {
    expect(mergeIngredients(["Ovo"], ["ovo", "leite"])).toEqual(["Ovo", "leite"]);
  });
});
