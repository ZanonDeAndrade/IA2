import { useEffect, useRef, useState } from "react";
import { BookOpen, History, RefreshCw, Sparkles, Target, X } from "lucide-react";
import { ClassBadge, ErrorNotice, Loading } from "../components/ChessUi";
import { coachApi } from "../lib/api";
import { ACTIVE, belongsTo } from "./coach";
import { CLASSES } from "../lib/chess";
import { MODES, SOURCES } from "./settings";

const moveLabel = (move) => `${move.numero}${move.cor === "white" ? "." : "…"} ${move.san ?? move.lance}`;

function splitAlternative(text) {
  const marker = text.search(/O Stockfish indica(?:va|vou|ou)? `/);
  return marker > 0 ? [text.slice(0, marker).trim(), text.slice(marker).trim()] : [text, ""];
}

function JobResult({ job, available, revealAlternative, onRegenerate, busy }) {
  const result = job.resultado;
  const [requestedAlternative, setRequestedAlternative] = useState(false);
  const showAlternative = revealAlternative || requestedAlternative;
  const [main, alternative] = splitAlternative(result.texto);
  const fromModel = result.fonte === "qwen3";
  return (
    <div className="explanation-content coach-result" data-fonte={result.fonte} data-indice={job.indice}>
      <div className="coach-tags">
        <span className={`source-tag ${fromModel ? "model" : "engine"}`}>
          {fromModel ? <Sparkles size={13} aria-hidden="true" /> : <Target size={13} aria-hidden="true" />}
          {fromModel && !result.ficha ? "Qwen3 · validado" : SOURCES[result.fonte]}
        </span>
        {result.tema && result.tema !== "outro" && <span className="theme-tag"><Target size={14} />{result.tema_label}</span>}
      </div>
      <p className="coach-text">{showAlternative ? result.texto : main}</p>
      {!showAlternative && alternative && (
        <button className="text-button" onClick={() => setRequestedAlternative(true)}>Mostrar a melhor alternativa</button>
      )}
      {result.ficha && (
        <div className="concept-source">
          <BookOpen size={16} />
          <span>Conceito consultado: <strong title={result.ficha.arquivo}>{result.ficha.titulo}</strong></span>
        </div>
      )}
      {!fromModel && (
        <p className="field-hint">
          {available
            ? "O Qwen3 não validou um texto próprio. Esta mensagem usa apenas dados verificados do Stockfish."
            : "O Qwen3 está indisponível. Esta mensagem usa apenas dados verificados do Stockfish."}
        </p>
      )}
      <p className="field-hint">
        Lances validados{result.cache ? " · reaproveitada do cache" : job.duracao_ms != null ? ` · pronta em ${(job.duracao_ms / 1000).toFixed(1)} s` : ""}
        {result.modelo ? ` · ${result.modelo}` : ""}
      </p>
      {available && (
        <button className="text-button" onClick={onRegenerate} disabled={busy}>
          <RefreshCw size={13} aria-hidden="true" /> {fromModel ? "Gerar outra explicação" : "Tentar gerar com o Qwen3"}
        </button>
      )}
    </div>
  );
}

export default function GameCoach({ game, move, coach, reviewing }) {
  const [viewing, setViewing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  const enabled = game.configuracoes.modo_treinador;
  const mode = game.configuracoes.modo_assistencia;
  const available = Boolean(coach.panel?.treinador.disponivel);
  const playerMoves = game.lances.filter((item) => item.autor === "jogador");
  const viewedMove = viewing != null ? playerMoves.find((item) => item.indice === viewing) : move;
  const candidate = viewedMove ? coach.byIndex.get(viewedMove.indice) : null;
  const job = belongsTo(candidate, viewedMove) ? candidate : null;
  const mismatch = Boolean(candidate && !job);
  const previous = (coach.panel?.explicacoes || [])
    .filter((item) => item.status === "concluida" && item.indice !== viewedMove?.indice)
    .slice().reverse();

  async function ask(forcar = false) {
    if (!viewedMove || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const created = await coachApi.explicar(game.id, viewedMove.indice, forcar, controller.signal);
      if (!controller.signal.aborted) {
        coach.upsert(created);
        coach.refresh();
      }
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message);
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      coach.upsert(await coachApi.cancelar(game.id, job.indice));
    } catch (err) {
      setError(err.message);
    }
  }

  const classification = viewedMove?.avaliacao?.classe;
  let body;
  if (!enabled) body = <p className="field-hint">Treinador desativado nesta partida.</p>;
  else if (!viewedMove) body = <p className="field-hint">Jogue um lance para receber a orientação do treinador.</p>;
  else if (mismatch) body = <ErrorNotice>A explicação recebida não corresponde a este lance e foi descartada.</ErrorNotice>;
  else if (!viewedMove.avaliacao) body = <p className="field-hint">Avalie o lance para pedir uma explicação.</p>;
  else if (!job) {
    const automatic = mode === "intensivo" || (mode === "treinador" && classification !== "aceitavel");
    body = (
      <div className="explanation-placeholder">
        <p>
          {mode === "livre"
            ? "Modo livre: o treinador só entra quando você pedir."
            : automatic
              ? "Aguardando a fila do treinador…"
              : "Lance aceitável. No modo Treinador, as explicações automáticas ficam para imprecisões e erros."}
        </p>
        <button className="button secondary" onClick={() => ask()} disabled={busy}>
          <Sparkles size={16} aria-hidden="true" />
          {classification === "aceitavel" ? "Comentar este lance" : "Explicar este lance"}
        </button>
      </div>
    );
  } else if (ACTIVE.has(job.status)) {
    body = (
      <div className="coach-waiting">
        <Loading>{job.status === "pendente" ? "Na fila do treinador. Continue jogando." : "O treinador está preparando a explicação…"}</Loading>
        <button className="text-button" onClick={cancel}><X size={13} aria-hidden="true" /> Cancelar</button>
      </div>
    );
  } else if (job.status === "concluida" && job.resultado) {
    body = (
      <JobResult key={`${job.id}:${job.concluido_em}`} job={job} available={available} busy={busy}
        revealAlternative={mode !== "intensivo" || game.configuracoes.revelar_alternativa}
        onRegenerate={() => ask(true)} />
    );
  } else {
    body = (
      <div className="explanation-placeholder">
        <p>{job.erro || "Não foi possível concluir a explicação."}</p>
        <button className="button secondary" onClick={() => ask(true)} disabled={busy}>
          <Sparkles size={16} aria-hidden="true" />
          {job.status === "ignorada" ? "Comentar mesmo assim" : "Tentar novamente"}
        </button>
      </div>
    );
  }

  return (
    <section className="panel play-coach" aria-labelledby="play-coach-title" data-testid="coach-panel">
      <div className="section-heading">
        <h2 id="play-coach-title"><Sparkles size={19} aria-hidden="true" /> Treinador inteligente</h2>
        <span className={`coach-status ${available ? "online" : "offline"}`} role="status">
          <span className={`status-dot ${available ? "online" : "offline"}`} />
          {coach.panel ? (available ? "Qwen3 conectado" : "Treinador indisponível") : "Verificando treinador"}
        </span>
      </div>
      <p className="field-hint">Modo {MODES[mode]?.label || mode}. {MODES[mode]?.description}</p>
      {coach.panel && !available && (
        <p className="notice coach-offline">{coach.panel.treinador.mensagem} A classificação e o histórico seguem funcionando.</p>
      )}
      {viewedMove && (
        <div className="play-coach-move" data-indice={viewedMove.indice}>
          <strong>
            {viewing != null ? "Explicação anterior · " : reviewing ? "Em revisão · " : "Seu lance "}
            {moveLabel(viewedMove)}
          </strong>
          <ClassBadge value={classification} />
          {viewing != null && (
            <button className="text-button" onClick={() => setViewing(null)}>Voltar ao lance atual</button>
          )}
        </div>
      )}
      {body}
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {coach.error && <p className="field-hint">Não foi possível atualizar o treinador: {coach.error}</p>}
      {previous.length > 0 && (
        <details className="coach-previous">
          <summary><History size={15} aria-hidden="true" /> Explicações anteriores ({previous.length})</summary>
          <div className="coach-previous-list">
            {previous.map((item) => (
              <button key={item.id} className="play-history-move" onClick={() => setViewing(item.indice)}
                aria-label={`Ver explicação do lance ${moveLabel(item.contexto)}`}>
                <b>{moveLabel(item.contexto)}</b>
                <span className="field-hint">{CLASSES[item.contexto.classe]?.label}</span>
                <span className="field-hint">{SOURCES[item.resultado?.fonte] || ""}</span>
              </button>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
