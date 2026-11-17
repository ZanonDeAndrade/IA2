import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { jsonResponse, mockFetch, output, recipe } from "./test/factories";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function ask(question: string, ingredients = "") {
  const user = userEvent.setup();
  if (ingredients) await user.type(screen.getByLabelText("Ingredientes que você tem"), ingredients);
  await user.type(screen.getByLabelText("Pergunta (opcional)"), question);
  await user.click(screen.getByRole("button", { name: "Buscar receitas" }));
  return user;
}

describe("App", () => {
  it("renderiza o formulário (smoke)", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Assistente Inteligente de Receitas" })).toBeInTheDocument();
    expect(screen.getByText("O que você tem na cozinha?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buscar receitas" })).toBeEnabled();
  });

  it("consulta positiva: envia ingredientes digitados e mostra card, faltantes e fonte", async () => {
    const fetchMock = mockFetch(
      jsonResponse(output({ recipes: [recipe({ compatibility: "PARTIAL", missing_ingredients: ["leite"] })] })),
    );
    render(<App />);
    await ask("O que posso fazer?", "ovo, queijo");
    expect(await screen.findByRole("heading", { name: "[TESTE] Omelete" })).toBeInTheDocument();
    expect(screen.getByText("Faltam ingredientes")).toBeInTheDocument();
    expect(screen.getByText("leite")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fontes consultadas" })).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0]![1]?.body as string)).toEqual({
      question: "O que posso fazer?",
      available_ingredients: ["ovo", "queijo"],
    });
  });

  it("loading bloqueia o botão até a resposta", async () => {
    let resolve!: (r: Response) => void;
    mockFetch(() => new Promise<Response>((r) => (resolve = r)));
    render(<App />);
    await ask("Receita de omelete?");
    expect(screen.getByRole("button", { name: "Buscando…" })).toBeDisabled();
    expect(screen.getByText("Consultando a base de receitas…")).toBeInTheDocument();
    resolve(jsonResponse(output()));
    expect(await screen.findByRole("button", { name: "Buscar receitas" })).toBeEnabled();
  });

  it("INSUFFICIENT não renderiza cards e oferece editar a consulta", async () => {
    mockFetch(jsonResponse(output({ status: "INSUFFICIENT", answer: "A base não tem receitas de lagosta.", recipes: [], sources: [] })));
    render(<App />);
    const user = await ask("Receita de lagosta?");
    expect(await screen.findByText("A base não tem receitas de lagosta.")).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Editar consulta" }));
    expect(screen.getByLabelText("Pergunta (opcional)")).toHaveFocus();
  });

  it("BLOCKED mostra a mensagem do guardrail", async () => {
    mockFetch(
      jsonResponse(
        output({ status: "BLOCKED", answer: "Só respondo sobre culinária.", recipes: [], sources: [], error: { code: "OUT_OF_SCOPE", message: "Só respondo sobre culinária." } }),
        422,
      ),
    );
    render(<App />);
    await ask("Capital da França?");
    expect(await screen.findByText("Não posso responder a essa consulta")).toBeInTheDocument();
    expect(screen.getByText("Só respondo sobre culinária.")).toBeInTheDocument();
  });

  it("falha de rede mostra erro e permite reenviar a mesma consulta", async () => {
    const fetchMock = mockFetch(new TypeError("Failed to fetch"), jsonResponse(output()));
    render(<App />);
    const user = await ask("Receita de omelete?");
    expect(await screen.findByRole("alert")).toHaveTextContent(/Não foi possível conectar ao servidor/);
    await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByRole("heading", { name: "[TESTE] Omelete" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]![1]?.body).toBe(fetchMock.mock.calls[0]![1]?.body);
  });

  it("ERROR do backend (503) mostra a mensagem e o request_id", async () => {
    mockFetch(
      jsonResponse(
        output({ status: "ERROR", request_id: "abc123", answer: "x", recipes: [], sources: [], error: { code: "LLM_UNAVAILABLE", message: "O modelo de linguagem está indisponível no momento." } }),
        503,
      ),
    );
    render(<App />);
    await ask("Receita de omelete?");
    expect(await screen.findByRole("alert")).toHaveTextContent("O modelo de linguagem está indisponível no momento.");
    expect(screen.getByText("Identificador da consulta: abc123")).toBeInTheDocument();
  });

  it("validação local impede envio de pergunta curta", async () => {
    const fetchMock = mockFetch();
    render(<App />);
    await ask("oi");
    expect(await screen.findByText("Revise a consulta")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("teclado: Enter adiciona ingrediente, botão remove, e envio pelo Enter do botão", async () => {
    const fetchMock = mockFetch(jsonResponse(output()));
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByLabelText("Ingredientes que você tem"), "ovo{Enter}leite{Enter}");
    await user.click(screen.getByRole("button", { name: "Remover leite" }));
    expect(screen.getByRole("list", { name: "Ingredientes informados" })).toHaveTextContent("ovo");
    expect(screen.queryByRole("button", { name: "Remover leite" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Pergunta (opcional)"), "Receita com ovo?");
    await user.tab();
    expect(screen.getByRole("button", { name: "Buscar receitas" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0]![1]?.body as string).available_ingredients).toEqual(["ovo"]);
  });

  it("texto da resposta é exibido como texto, não como HTML", async () => {
    mockFetch(jsonResponse(output({ answer: '<img src=x onerror="alert(1)">Receita' })));
    const { container } = render(<App />);
    await ask("Receita de omelete?");
    expect(await screen.findByText('<img src=x onerror="alert(1)">Receita')).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
