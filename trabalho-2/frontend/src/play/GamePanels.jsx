import { useEffect, useRef, useState } from "react";
import { Chess } from "chess.js";
import { ChartNoAxesCombined, Flag, Lightbulb, List, Play, Swords, Trophy } from "lucide-react";
import { ClassBadge, ErrorNotice } from "../components/ChessUi";
import { api, writeCache } from "../lib/api";
import { CLASSES, evaluation } from "../lib/chess";
import { COLORS, END_REASONS, LEVELS, MODES, playPath } from "./settings";

const FEEDBACK = {
  aceitavel: "Você realizou um movimento adequado para a posição.",
  imprecisao: "Existia uma alternativa melhor.",
  erro: "Seu movimento prejudicou sua posição.",
  erro_grave: "Seu movimento provocou uma perda significativa.",
};

export function GameControls({
  game, active, playable, status, evaluationPoint, tip, aidError, onRetryAid, visuals, onVisuals, onSettings,
  onResign, onDraw,
}) {
  const [confirm, setConfirm] = useState("");
  const [drawMove, setDrawMove] = useState("");
  const draw = game.empate_reivindicavel;
  const drawOptions = Object.entries(draw?.por_lance || {});
  const hasDraw = draw?.agora || drawOptions.length > 0;
  const claim = draw?.agora ? null : drawOptions.some(([uci]) => uci === drawMove) ? drawMove : drawOptions[0]?.[0];

  return (
    <section className="panel play-controls" aria-labelledby="play-controls-title">
      <h2 id="play-controls-title">Partida</h2>
      <p className="play-status" role="status">{status}</p>
      <dl className="play-facts">
        <div><dt>Dificuldade</dt><dd>{LEVELS[game.dificuldade]}</dd></div>
        <div><dt>Sua cor</dt><dd>{COLORS[game.cor_do_jogador]}</dd></div>
        {game.configuracoes.mostrar_avaliacao && (
          <div><dt>Avaliação (sua cor)</dt><dd>{evaluation(evaluationPoint && { avaliacao: evaluationPoint })}</dd></div>
        )}
      </dl>
      {tip && <p className="play-tip" role="status"><Lightbulb size={17} aria-hidden="true" /> Melhor lance <strong>{tip.san}</strong></p>}
      {aidError && <ErrorNotice onRetry={onRetryAid}>{aidError}</ErrorNotice>}
      {active && game.configuracoes.modo_treinador && (
        <div className="mode-switch">
          <label htmlFor="play-mode">Assistência</label>
          <select id="play-mode" value={game.configuracoes.modo_assistencia} disabled={!playable}
            onChange={(event) => onSettings({ modo_assistencia: event.target.value })}>
            {Object.entries(MODES).map(([id, mode]) => <option key={id} value={id}>{mode.label}</option>)}
          </select>
        </div>
      )}
      {active && game.configuracoes.modo_treinador && game.configuracoes.modo_assistencia === "intensivo" && (
        <label className="play-toggle">
          <input type="checkbox" checked={game.configuracoes.revelar_alternativa} disabled={!playable}
            onChange={(event) => onSettings({ revelar_alternativa: event.target.checked })} />
          Mostrar a melhor alternativa nos comentários
        </label>
      )}
      {active && (
        <div className="play-actions">
          {hasDraw && (
            <button className="button secondary" onClick={() => setConfirm("draw")} disabled={!playable}>
              Reivindicar empate
            </button>
          )}
          <button className="button secondary" onClick={() => setConfirm("resign")} disabled={!playable}>
            <Flag size={16} aria-hidden="true" /> Desistir
          </button>
        </div>
      )}
      <label className="play-toggle">
        <input type="checkbox" checked={visuals} onChange={(event) => onVisuals(event.target.checked)} />
        Setas no tabuleiro
      </label>
      {active && confirm === "resign" && (
        <div className="play-confirm" role="group" aria-label="Confirmar desistência">
          <p>Desistir encerra a partida com vitória do Stockfish.</p>
          <div className="play-actions">
            <button className="button primary" disabled={!playable} onClick={() => { setConfirm(""); onResign(); }}>
              Confirmar desistência
            </button>
            <button className="button secondary" onClick={() => setConfirm("")}>Cancelar</button>
          </div>
        </div>
      )}
      {active && confirm === "draw" && hasDraw && (
        <div className="play-confirm" role="group" aria-label="Confirmar empate">
          {draw.agora ? <p>{END_REASONS[draw.agora]}</p> : (
            <>
              <label htmlFor="play-draw-move">Lance para reivindicar o empate</label>
              <select id="play-draw-move" value={claim}
                onChange={(event) => setDrawMove(event.target.value)}>
                {drawOptions.map(([uci, reason]) => {
                  const move = new Chess(game.fen).move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
                  return <option key={uci} value={uci}>{move.san} · {END_REASONS[reason]}</option>;
                })}
              </select>
            </>
          )}
          <div className="play-actions">
            <button className="button primary" disabled={!playable} onClick={() => { setConfirm(""); onDraw(claim); }}>
              Confirmar empate
            </button>
            <button className="button secondary" onClick={() => setConfirm("")}>Cancelar</button>
          </div>
        </div>
      )}
    </section>
  );
}

export function GameFeedback({ move, reviewing, onEvaluate, disabled }) {
  const classification = move?.avaliacao?.classe;
  const missing = reviewing ? "Selecione um dos seus lances para ver a classificação." : "A classificação aparece após seu primeiro lance.";
  return (
    <section className="panel play-feedback" aria-labelledby="play-feedback-title">
      <h2 id="play-feedback-title">{reviewing ? "Classificação em revisão" : "Última classificação"}</h2>
      <div aria-live="polite">
        {move && <strong className="play-move-caption">{move.numero}{move.cor === "white" ? "." : "…"} {move.san}</strong>}
        {classification ? (
          <>
            <ClassBadge value={classification} />
            <p>{FEEDBACK[classification]}</p>
            <details className="engine-line">
              <summary>Ver avaliação do lance</summary>
              {move.avaliacao.melhor_lance && <p>Melhor alternativa {move.avaliacao.melhor_lance}</p>}
              <p>Avaliação após o lance {evaluation({ avaliacao: move.avaliacao.avaliacao_depois })}</p>
              {Number.isFinite(move.avaliacao.queda) && (
                <p>Perda de chance {move.avaliacao.queda.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} p.p.</p>
              )}
              {move.avaliacao.linha_motor?.length > 0 && <p>Variante {move.avaliacao.linha_motor.join(" · ")}</p>}
            </details>
          </>
        ) : <p>{move ? "Ainda não há classificação para este lance." : missing}</p>}
        {move && !classification && (
          <button className="button secondary" onClick={onEvaluate} disabled={disabled}>Avaliar lance</button>
        )}
      </div>
    </section>
  );
}

export function GameHistory({ moves, active, revision, onReview }) {
  const scroll = useRef(null);
  const moveCount = moves.length;
  useEffect(() => {
    if (active && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [active, moveCount]);
  const pairs = [];
  for (let i = 0; i < moves.length; i += 2) pairs.push(moves.slice(i, i + 2));

  function cell(move) {
    if (!move) return null;
    const classification = move.avaliacao?.classe;
    const label = `${move.numero} ${COLORS[move.cor].toLowerCase()}, ${move.san}, ${move.autor === "ia" ? "Stockfish" : "você"}${classification ? `, ${CLASSES[classification].label}` : ""}`;
    const content = <><b>{move.san}</b>{classification && <ClassBadge value={classification} />}</>;
    return active ? <span className="play-history-move" title={label}>{content}</span> : (
      <button className="play-history-move" aria-label={label} aria-pressed={revision === move.indice}
        onClick={() => onReview(move.indice)}>{content}</button>
    );
  }

  return (
    <section className="panel play-history" aria-labelledby="play-history-title">
      <h2 id="play-history-title"><List size={19} aria-hidden="true" /> Histórico de movimentos</h2>
      {!active && (
        <div className="play-actions">
          <button className="button secondary" aria-pressed={revision === 0} onClick={() => onReview(0)}>Posição inicial</button>
          <button className="button secondary" aria-pressed={revision === null} onClick={() => onReview(null)}>Posição atual</button>
        </div>
      )}
      {moves.length === 0 ? <p className="field-hint">Nenhum movimento registrado.</p> : (
        <div className="play-history-scroll" ref={scroll} tabIndex={0} aria-label="Lista de movimentos">
          <table>
            <thead><tr><th scope="col">Nº</th><th scope="col">Brancas</th><th scope="col">Pretas</th></tr></thead>
            <tbody>
              {pairs.map(([white, black]) => (
                <tr key={white.indice}>
                  <th scope="row">{white.numero}</th><td>{cell(white)}</td><td>{cell(black)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function GameResult({ game, reportPath }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const work = useRef(null);
  useEffect(() => () => work.current?.abort(), []);
  const score = game.resultado;
  const win = score === (game.cor_do_jogador === "white" ? "1-0" : "0-1");
  const result = score === "*" ? "Partida encerrada" : score === "1/2-1/2" ? "Empate" : win ? "Você venceu" : "Stockfish venceu";
  const stats = game.estatisticas;
  const classified = stats.lances_do_jogador_analisados;

  async function analyze() {
    if (work.current || !game.partida_analise_id) return;
    const controller = new AbortController();
    work.current = controller;
    setBusy(true);
    setError("");
    try {
      const id = game.partida_analise_id;
      const job = await api.analisar(id, controller.signal);
      if (controller.signal.aborted) return;
      writeCache(`task:${id}`, job.tarefa_id);
      window.location.hash = `#/analise/${encodeURIComponent(id)}`;
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message);
    } finally {
      work.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section className="panel play-result" aria-labelledby="play-result-title">
      <div className="section-heading">
        <div>
          <h2 id="play-result-title"><Trophy size={21} aria-hidden="true" /> {result} {score !== "*" && <span className="badge">{score}</span>}</h2>
          <p>{END_REASONS[game.motivo] || game.motivo}</p>
        </div>
      </div>
      <dl className="play-facts">
        <div><dt>Sua cor</dt><dd>{COLORS[game.cor_do_jogador]}</dd></div>
        <div><dt>Dificuldade</dt><dd>{LEVELS[game.dificuldade]}</dd></div>
        <div><dt>Meios-lances</dt><dd>{game.lances.length}</dd></div>
        <div><dt>Seus lances avaliados</dt><dd>{classified}</dd></div>
        <div><dt>Precisão</dt><dd>{stats.precisao == null ? "—" : `${stats.precisao.toLocaleString("pt-BR")}%`}</dd></div>
      </dl>
      {classified > 0 && (
        <div className="play-result-classes" aria-label="Resumo do desempenho">
          {Object.keys(CLASSES).map((key) => (
            <span key={key}><ClassBadge value={key} /> {game.lances.filter((move) => move.avaliacao?.classe === key).length}</span>
          ))}
        </div>
      )}
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <div className="play-actions">
        <a className="button primary" href={playPath()}><Play size={16} aria-hidden="true" /> Jogar novamente</a>
        <button className="button secondary" disabled={busy || !game.partida_analise_id} onClick={analyze}>
          <Swords size={16} aria-hidden="true" /> {busy ? "Abrindo análise…" : "Analisar partida"}
        </button>
        <a className="button secondary" href={game.usuario ? `#/relatorio/${encodeURIComponent(game.usuario)}` : `#${reportPath}`}>
          <ChartNoAxesCombined size={16} aria-hidden="true" /> Ver meu progresso
        </a>
        <a className="button secondary" href="#/">Voltar ao início</a>
      </div>
      {!game.partida_analise_id && <p className="field-hint">Jogue pelo menos um lance para abrir a análise da partida.</p>}
    </section>
  );
}
