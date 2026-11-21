export const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export async function request(path, { body, signal, timeout = 155000 } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail
            .map(
              (item) =>
                `${item.loc?.slice(1).join(".") || "Entrada"}: ${item.msg}`,
            )
            .join("; ")
        : data.detail;
      throw new Error(
        detail ||
          `O serviço retornou erro ${response.status}. Tente novamente.`,
      );
    }
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

export const api = {
  importar: (body, signal) =>
    request("/api/partidas/importar", { body, signal }),
  analisar: (id, signal) =>
    request(`/api/partidas/${encodeURIComponent(id)}/analisar`, {
      body: {},
      signal,
    }),
  partida: (id, signal) =>
    request(`/api/partidas/${encodeURIComponent(id)}`, { signal }),
  tarefa: (id, signal) =>
    request(`/api/tarefas/${encodeURIComponent(id)}`, { signal }),
  explicar: (body, signal) => request("/api/explicar", { body, signal }),
  chat: (body, signal) => request("/api/chat", { body, signal }),
  relatorio: (usuario, signal) =>
    request(`/api/relatorio/${encodeURIComponent(usuario)}`, { signal }),
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
