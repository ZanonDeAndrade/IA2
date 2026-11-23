export const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export async function request(path, { body, method = body === undefined ? "GET" : "POST", signal, timeout = 15000, valid } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = Array.isArray(data?.detail)
        ? data.detail
            .map(
              (item) =>
                `${item.loc?.slice(1).join(".") || "Entrada"}: ${item.msg}`,
            )
            .join("; ")
        : data?.detail;
      const error = new Error(
        detail ||
          `O serviço retornou erro ${response.status}. Tente novamente.`,
      );
      error.status = response.status;
      throw error;
    }
    if (!data || typeof data !== "object" || Array.isArray(data) || (valid && !valid(data)))
      throw new Error("O servidor devolveu uma resposta inválida. Tente novamente.");
    return data;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error.name === "AbortError")
      throw new Error(
        "O serviço demorou a responder. Tente novamente em instantes.",
      );
    if (error instanceof TypeError)
      throw new Error(
        "Não foi possível conectar ao servidor. Verifique se a API está em execução.",
      );
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

const gameId = (game) => typeof game?.id === "string" && game.id.length > 0;
const validAnswer = (data, field) =>
  typeof data.validada === "boolean" && (!data.validada || typeof data[field] === "string");

export const api = {
  importar: (body, signal) =>
    request("/api/partidas/importar", {
      body, signal, timeout: 45000, valid: (d) => Array.isArray(d.partidas) && d.partidas.every(gameId),
    }),
  analisar: (id, signal) =>
    request(`/api/partidas/${encodeURIComponent(id)}/analisar`, {
      method: "POST", signal, valid: (d) => typeof d.tarefa_id === "string" && !!d.tarefa_id,
    }),
  partida: (id, signal) =>
    request(`/api/partidas/${encodeURIComponent(id)}`, {
      signal, valid: (d) => d.id === id && typeof d.fen_inicial === "string" && Array.isArray(d.lances) && Array.isArray(d.curva_avaliacao),
    }),
  tarefa: (id, signal) =>
    request(`/api/tarefas/${encodeURIComponent(id)}`, {
      signal, valid: (d) => ["pendente", "em_andamento", "concluida", "erro"].includes(d.status) && Number.isFinite(d.progresso?.percentual),
    }),
  explicar: (body, signal) => request("/api/explicar", { body, signal, timeout: 155000, valid: (d) => validAnswer(d, "texto") }),
  chat: (body, signal) => request("/api/chat", { body, signal, timeout: 155000, valid: (d) => validAnswer(d, "resposta") }),
  relatorio: (usuario, signal) =>
    request(`/api/relatorio/${encodeURIComponent(usuario)}`, {
      signal, timeout: 25000, valid: (d) => Number.isInteger(d.partidas_analisadas) && [d.temas_fracos, d.evolucao, d.puzzles_recomendados].every(Array.isArray),
    }),
};

// Caches separados por URL impedem misturar servidores de desenvolvimento.
const prefix = `lance:v1:${API_URL}:`;
export function readCache(key, fallback = null) {
  try {
    return JSON.parse(localStorage.getItem(prefix + key)) ?? fallback;
  } catch {
    return fallback;
  }
}
export function writeCache(key, value) {
  try {
    localStorage.setItem(prefix + key, JSON.stringify(value));
  } catch {
    /* armazenamento indisponível */
  }
}
