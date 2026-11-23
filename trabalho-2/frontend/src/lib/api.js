export const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export async function request(path, { body, headers, method = body === undefined ? "GET" : "POST", signal, timeout = 15000, valid } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: body === undefined ? headers : { ...headers, "Content-Type": "application/json" },
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

const playEndpoint = (id) => `/api/jogo/${encodeURIComponent(id)}`;
const validPlayState = (game) =>
  gameId(game) && Number.isInteger(game.versao) && typeof game.fen === "string"
  && ["white", "black"].includes(game.cor_do_jogador)
  && ["em_andamento", "encerrada"].includes(game.status)
  && game.configuracoes && game.estatisticas && [game.lances, game.lances_legais].every(Array.isArray);
const playRequest = (id, suffix, signal, body) =>
  request(playEndpoint(id) + suffix, {
    signal, body, timeout: 50000, valid: (game) => validPlayState(game) && game.id === id,
  });

export const playApi = {
  iniciar: (body, signal, sessao) => request("/api/jogo/iniciar", {
    body, signal, timeout: 50000, valid: validPlayState,
    headers: sessao ? { "X-Sessao-Jogo": sessao } : undefined,
  }),
  listar: (sessao, signal) => request("/api/jogo/partidas", {
    signal, headers: { "X-Sessao-Jogo": sessao },
    valid: (data) => Array.isArray(data.partidas) && data.partidas.every(gameId),
  }),
  partida: (id, signal) => playRequest(id, "", signal),
  mover: (id, versao, lance, signal) => playRequest(id, "/mover", signal, { versao, lance }),
  desistir: (id, versao, signal) => playRequest(id, "/desistir", signal, { versao }),
  empatar: (id, versao, lance, signal) =>
    playRequest(id, "/reivindicar-empate", signal, { versao, lance }),
  avaliar: (id, versao, indice, signal) =>
    playRequest(id, `/historico/${indice}/avaliar`, signal, { versao }),
  posicao: (id, versao, recomendar, signal) => request(
    `${playEndpoint(id)}/posicao?versao=${versao}&recomendar=${recomendar}`,
    { signal, timeout: 50000, valid: (data) => data.versao === versao && Boolean(data.avaliacao)
      && (!recomendar || typeof data.dica?.uci === "string") },
  ),
  explicar: (id, indice, signal) => request(`${playEndpoint(id)}/historico/${indice}/explicar`, {
    method: "POST", signal, timeout: 155000, valid: (data) => validAnswer(data, "texto"),
  }),
  configurar: (id, body, signal) => playRequest(id, "/configuracoes", signal, body),
};

// Treinador: as respostas trazem o vínculo com o lance (índice, ID e FENs) ou a versão da posição.
const validJob = (data) => typeof data.id === "string" && Number.isInteger(data.indice)
  && typeof data.contexto?.lance_id === "string" && typeof data.contexto?.fen_antes === "string";
export const coachApi = {
  painel: (id, signal) => request(`${playEndpoint(id)}/treinador`, {
    signal, timeout: 15000,
    valid: (d) => d.jogo_id === id && Array.isArray(d.explicacoes) && d.explicacoes.every(validJob) && Array.isArray(d.dicas),
  }),
  explicar: (id, indice, forcar, signal) => request(`${playEndpoint(id)}/explicacoes/${indice}`, {
    body: { forcar }, signal, valid: (d) => validJob(d) && d.indice === indice,
  }),
  cancelar: (id, indice, signal) => request(`${playEndpoint(id)}/explicacoes/${indice}/cancelar`, {
    method: "POST", signal, valid: (d) => validJob(d) && d.indice === indice,
  }),
  dica: (id, versao, nivel, signal) => request(`${playEndpoint(id)}/dica`, {
    body: { versao, nivel }, signal, timeout: 50000,
    valid: (d) => d.jogo_id === id && d.versao === versao && d.nivel === nivel && typeof d.texto === "string",
  }),
  chat: (id, body, signal) => request(`${playEndpoint(id)}/chat`, {
    body, signal, timeout: 155000,
    valid: (d) => d.jogo_id === id && d.versao === body.versao && typeof d.resposta === "string",
  }),
  relatorio: (id, signal) => request(`${playEndpoint(id)}/relatorio`, {
    signal, timeout: 30000, valid: (d) => d.id === id && Array.isArray(d.lances_criticos) && Array.isArray(d.puzzles),
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
