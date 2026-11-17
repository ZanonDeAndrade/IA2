import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { recipe } from "../test/factories";
import { RecipeCard } from "./RecipeCard";

describe("RecipeCard", () => {
  it("mostra compatibilidade, disponíveis e faltantes", () => {
    render(<RecipeCard recipe={recipe({ compatibility: "PARTIAL", available_ingredients: ["ovo"], missing_ingredients: ["leite", "farinha"] })} />);
    expect(screen.getByText("Faltam ingredientes")).toBeInTheDocument();
    expect(screen.getByText("leite, farinha")).toBeInTheDocument();
    expect(screen.getByText("ovo")).toBeInTheDocument();
  });

  it("modo de preparo só aparece ao expandir, pelo teclado", async () => {
    const user = userEvent.setup();
    render(<RecipeCard recipe={recipe()} />);
    const toggle = screen.getByRole("button", { name: "Ver preparo" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Bata os ovos.")).not.toBeVisible();
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Ocultar preparo" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Bata os ovos.")).toBeVisible();
  });

  it("não inventa preparo quando a fonte não trouxe instruções", () => {
    render(<RecipeCard recipe={recipe({ instructions: [] })} />);
    expect(screen.queryByRole("button", { name: "Ver preparo" })).not.toBeInTheDocument();
    expect(screen.getByText("O modo de preparo não foi recuperado da fonte.")).toBeInTheDocument();
  });

  it("ingredientes mostram quantidade, opcional e observação; campos ausentes ficam de fora", () => {
    render(<RecipeCard recipe={recipe()} />);
    expect(screen.getByText("2 ovos")).toBeInTheDocument();
    expect(screen.getByText("queijo (opcional) — ralado")).toBeInTheDocument();
    expect(screen.getByText("Tempo: 10 minutos")).toBeInTheDocument();
    expect(screen.queryByText(/Rendimento/)).not.toBeInTheDocument();
  });

  it("sem ingredientes informados não mostra Tenho/Faltam", () => {
    render(<RecipeCard recipe={recipe({ compatibility: "NOT_EVALUATED", available_ingredients: [], missing_ingredients: [] })} />);
    expect(screen.getByText("Compatibilidade não avaliada")).toBeInTheDocument();
    expect(screen.queryByText("Faltam")).not.toBeInTheDocument();
  });
});
