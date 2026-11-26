import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { output, recipe } from "../test/factories";
import { groupRecipes, ResultList } from "./ResultList";

describe("ResultList", () => {
  it("separa o que dá para preparar agora do que exige ingredientes adicionais", () => {
    const recipes = [
      recipe({ recipe_id: "p-v1", title: "[TESTE] Panqueca", compatibility: "PARTIAL", missing_ingredients: ["farinha"] }),
      recipe({ recipe_id: "c-v1", title: "[TESTE] Omelete", compatibility: "COMPLETE" }),
    ];
    render(<ResultList result={output({ recipes })} />);
    const now = screen.getByRole("region", { name: /Você pode preparar agora/ });
    const later = screen.getByRole("region", { name: /Com ingredientes adicionais/ });
    expect(within(now).getByRole("heading", { name: "[TESTE] Omelete" })).toBeInTheDocument();
    expect(within(later).getByRole("heading", { name: "[TESTE] Panqueca" })).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument(); // há receita completa
  });

  it("avisa quando nenhuma receita é totalmente compatível (situação B)", () => {
    render(<ResultList result={output({ recipes: [recipe({ compatibility: "PARTIAL", missing_ingredients: ["açúcar"] })] })} />);
    expect(screen.getByRole("note")).toHaveTextContent("Nenhuma receita totalmente compatível");
    expect(screen.queryByText("Você pode preparar agora")).not.toBeInTheDocument();
  });

  it("sem ingredientes informados mostra só 'Receitas encontradas'", () => {
    const groups = groupRecipes([recipe({ compatibility: "NOT_EVALUATED", available_ingredients: [], missing_ingredients: [] })]);
    expect(groups.map((g) => g.title)).toEqual(["Receitas encontradas"]);
  });
});
