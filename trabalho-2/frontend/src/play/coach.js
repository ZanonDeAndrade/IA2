import { useEffect, useMemo, useState } from "react";
import { coachApi } from "../lib/api";

export const ACTIVE = new Set(["pendente", "em_andamento"]);

// Uma explicação só pertence ao lance se o ID e os dois FENs coincidirem.
export function belongsTo(job, move) {
  return Boolean(job && move && job.indice === move.indice && job.contexto.lance_id === move.id
    && job.contexto.fen_antes === move.fen_antes && job.contexto.fen_depois === move.fen_depois);
}

export function useCoach(id, version, enabled) {
  const [panel, setPanel] = useState(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const pending = Boolean(panel?.explicacoes.some((job) => ACTIVE.has(job.status)));
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    coachApi.painel(id, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setPanel(data);
        setError("");
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message);
      });
    return () => controller.abort();
  }, [id, version, tick, enabled]);
  useEffect(() => {
    if (!enabled) return;
    // Consulta curta só enquanto houver explicação na fila. Sem fila, revalida o status do modelo de vez em quando.
    const timer = setTimeout(() => setTick((n) => n + 1), pending ? 2000 : 30000);
    return () => clearTimeout(timer);
  }, [pending, panel, enabled]);
  const byIndex = useMemo(() => new Map((panel?.explicacoes || []).map((job) => [job.indice, job])), [panel]);
  function upsert(job) {
    setPanel((current) => current && ({
      ...current,
      explicacoes: [...current.explicacoes.filter((item) => item.indice !== job.indice), job]
        .sort((a, b) => a.indice - b.indice),
    }));
  }
  return { panel, byIndex, error, refresh: () => setTick((n) => n + 1), upsert };
}

export function revealedTip(game, coach) {
  const hint = (coach.panel?.dicas || []).find((item) => item.versao === game.versao && item.fen === game.fen
    && item.nivel === 3 && item.lance);
  return hint?.lance || null;
}
