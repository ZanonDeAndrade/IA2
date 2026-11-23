import { useEffect, useRef, useState } from "react";
import { BookOpen, Lightbulb } from "lucide-react";
import { ErrorNotice, Loading } from "../components/ChessUi";
import { coachApi } from "../lib/api";

const STEPS = {
  1: "Preciso de uma dica",
  2: "Mais uma dica",
  3: "Mostrar o lance sugerido",
};
const TITLES = { 1: "Objetivo", 2: "Onde olhar", 3: "Lance do Stockfish" };

export function HintHistory({ game, hints }) {
  const positions = new Map();
  for (const hint of hints || []) {
    if (game.status === "em_andamento" && hint.versao === game.versao) continue;
    if (!positions.has(hint.versao)) positions.set(hint.versao, []);
    positions.get(hint.versao).push(hint);
  }
  if (!positions.size) return null;
  return (
    <section className="panel play-hints" aria-labelledby="hint-history-title">
      <h2 id="hint-history-title"><Lightbulb size={19} aria-hidden="true" /> Histórico de dicas</h2>
      {Array.from(positions, ([version, steps]) => {
        const move = game.lances.find((item) => item.fen_depois === steps[0].fen);
        return (
          <details key={version} className="coach-previous">
            <summary>{move ? `Após ${move.numero}${move.cor === "white" ? "." : "…"} ${move.san}` : "Posição inicial"}</summary>
            <ol className="hint-steps">
              {steps.map((hint) => (
                <li key={hint.nivel}>
                  <b>{TITLES[hint.nivel]}</b>
                  <p>{hint.texto.replace(/`/g, "")}</p>
                  {hint.conceito && <p className="field-hint">{hint.conceito}</p>}
                  {hint.ficha && <p className="field-hint">Ficha {hint.ficha.titulo}</p>}
                </li>
              ))}
            </ol>
          </details>
        );
      }).reverse()}
    </section>
  );
}

// As dicas ficam salvas no servidor por versão da partida e somem quando a posição muda.
export default function GameHints({ game, playable, coach }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmReveal, setConfirmReveal] = useState(false);
  const [local, setLocal] = useState([]);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  const saved = (coach.panel?.dicas || []).filter((hint) => hint.versao === game.versao && hint.fen === game.fen);
  const hints = [...saved, ...local.filter((hint) => hint.versao === game.versao && hint.fen === game.fen
    && !saved.some((item) => item.nivel === hint.nivel))].sort((a, b) => a.nivel - b.nivel);
  const next = (hints.at(-1)?.nivel || 0) + 1;

  async function ask(level) {
    if (request.current || !playable) return;
    const controller = new AbortController();
    request.current = controller;
    const version = game.versao;
    setBusy(true);
    setError("");
    setConfirmReveal(false);
    try {
      const hint = await coachApi.dica(game.id, version, level, controller.signal);
      if (!controller.signal.aborted && hint.versao === version) {
        setLocal((items) => [...items, hint]);
        coach.refresh();
      }
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message);
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  if (game.status !== "em_andamento") return null;
  return (
    <section className="panel play-hints" aria-labelledby="play-hints-title" data-testid="hint-panel">
      <h2 id="play-hints-title"><Lightbulb size={19} aria-hidden="true" /> Dicas em etapas</h2>
      {!hints.length && (
        <p className="field-hint">A primeira dica aponta o objetivo. O lance só aparece na terceira etapa, se você pedir.</p>
      )}
      <ol className="hint-steps">
        {hints.map((hint) => (
          <li key={hint.nivel} data-nivel={hint.nivel}>
            <b>{TITLES[hint.nivel]}</b>
            <p>{hint.texto.replace(/`/g, "")}</p>
            {hint.ficha && (
              <p className="concept-source">
                <BookOpen size={15} aria-hidden="true" />
                <span>
                  Ficha <strong title={hint.ficha.arquivo}>{hint.ficha.titulo}</strong>
                  {hint.conceito ? `: ${hint.conceito}` : ""}
                </span>
              </p>
            )}
          </li>
        ))}
      </ol>
      {busy && <Loading>Consultando o Stockfish…</Loading>}
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {next <= 3 && !confirmReveal && (
        <button className="button secondary" disabled={!playable || busy}
          onClick={() => (next === 3 ? setConfirmReveal(true) : ask(next))}>
          <Lightbulb size={16} aria-hidden="true" /> {STEPS[next]}
        </button>
      )}
      {confirmReveal && (
        <div className="play-confirm" role="group" aria-label="Confirmar revelação do lance">
          <p>Isso mostra o lance sugerido pelo Stockfish e encerra o desafio desta posição.</p>
          <div className="play-actions">
            <button className="button primary" onClick={() => ask(3)} disabled={!playable || busy}>Revelar o lance</button>
            <button className="button secondary" onClick={() => setConfirmReveal(false)}>Continuar tentando</button>
          </div>
        </div>
      )}
      <p className="field-hint">Dicas verificadas pelo Stockfish e pelas regras do xadrez, sem texto gerado pela IA.</p>
    </section>
  );
}
