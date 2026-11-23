import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorNotice, Loading } from "../components/ChessUi";
import { playApi, readCache, writeCache } from "../lib/api";
import GameBoard from "./GameBoard";
import GameChat from "./GameChat";
import GameCoach from "./GameCoach";
import GameHints, { HintHistory } from "./GameHints";
import { revealedTip, useCoach } from "./coach";
import { GameControls, GameFeedback, GameHistory, GameResult } from "./GamePanels";
import GameReport from "./GameReport";
import GameSetup from "./GameSetup";
import { playPath } from "./settings";
import "./play.css";

export default function PlayPage({ id, reportPath }) {
  return id ? <GameSession id={id} reportPath={reportPath} /> : <GameSetup />;
}

function GameSession({ id, reportPath }) {
  const [game, setGame] = useState(null);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState("");
  const [needsSync, setNeedsSync] = useState(false);
  const [reload, setReload] = useState(0);
  const [revision, setRevision] = useState(null);
  const [visuals, setVisuals] = useState(() => readCache(`play:visuals:${id}`, true));
  const action = useRef(null);
  const accept = useCallback((data) => {
    setGame(data);
    setNeedsSync(false);
    if (data.status === "em_andamento") writeCache("play:active", data.id);
    else if (readCache("play:active") === data.id) writeCache("play:active", null);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const data = await playApi.partida(id, controller.signal);
        if (controller.signal.aborted) return;
        accept(data);
        if (data.processando) timer = setTimeout(load, 1000);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err.status === 404 && readCache("play:active") === id) writeCache("play:active", null);
        setError(err.message);
        setNeedsSync(true);
      }
    }
    load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, reload, accept]);

  useEffect(() => () => action.current?.abort(), []);
  useEffect(() => writeCache(`play:visuals:${id}`, visuals), [id, visuals]);
  const active = game?.status === "em_andamento";
  const playable = active && game.vez === "jogador" && !game.processando && !pending && !needsSync;
  const coachEnabled = game?.configuracoes.modo_treinador;
  const aid = usePositionAid(game, playable);
  const coach = useCoach(id, game?.versao, coachEnabled);
  const retry = () => {
    setError("");
    setNeedsSync(true);
    setReload((previous) => previous + 1);
  };

  async function perform(kind, run, preview = null) {
    if (!game || action.current || game.processando || needsSync || (kind !== "evaluate" && !playable)) return;
    const controller = new AbortController();
    action.current = controller;
    setPending({ kind, ...preview });
    setError("");
    try {
      const data = await run(controller.signal);
      if (!controller.signal.aborted) accept(data);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err.message);
      setPending({ kind: "sync" });
      try {
        const data = await playApi.partida(id, controller.signal);
        if (controller.signal.aborted) return;
        accept(data);
        if (data.processando) setReload((previous) => previous + 1);
        if (preview && data.lances[game.lances.length]?.uci === preview.uci) setError("");
      } catch {
        if (!controller.signal.aborted) setNeedsSync(true);
      }
    } finally {
      action.current = null;
      if (!controller.signal.aborted) setPending(null);
    }
  }

  if (!game) {
    return (
      <>
        <div className="page-heading"><h1>Jogar contra IA<span className="accent">.</span></h1></div>
        {error ? <ErrorNotice onRetry={retry}>{error}</ErrorNotice> : <Loading>Recuperando partida…</Loading>}
        {error && <a className="button secondary" href={playPath()}>Configurar outra partida</a>}
      </>
    );
  }

  const reviewing = !active && revision !== null;
  const reviewedMove = reviewing ? game.lances.find((move) => move.indice === revision) : null;
  const currentMove = game.lances.at(-1);
  const lastPlayerMove = game.lances.findLast((move) => move.autor === "jogador");
  const reviewFEN = reviewedMove?.fen_depois || game.fen_inicial;
  const visibleFEN = reviewing ? reviewFEN : game.fen;
  const lastMove = reviewing ? reviewedMove?.uci : currentMove?.uci;
  const feedback = reviewing ? reviewedMove?.autor === "jogador" ? reviewedMove : null : lastPlayerMove;
  const score = reviewing
    ? (reviewedMove?.avaliacao?.avaliacao_depois || game.lances.find((move) => move.fen_antes === reviewFEN)?.avaliacao?.avaliacao_antes)
    : aid.data?.avaliacao || (!active ? currentMove?.avaliacao?.avaliacao_depois : null);
  let status = "Sua vez";
  if (reviewing) status = reviewedMove ? `Revisão · após ${reviewedMove.san}` : "Revisão · posição inicial";
  else if (!active) status = "Partida encerrada · posição atual";
  else if (needsSync && error) status = "Posição aguardando sincronização";
  else if (needsSync || pending?.kind === "sync") status = "Sincronizando com o servidor…";
  else if (pending?.kind === "move") status = `Stockfish processando ${pending.san}…`;
  else if (pending?.kind === "evaluate") status = "Avaliando o lance…";
  else if (pending?.kind === "config") status = "Atualizando o modo do treinador…";
  else if (pending) status = "Encerrando partida…";
  else if (game.processando || game.vez === "ia") status = "Stockfish processando…";
  else if (game.em_xeque) status = "Sua vez · você está em xeque";

  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Jogar contra IA<span className="accent">.</span></h1>
          {active && <p>Partida contra o Stockfish</p>}
        </div>
      </div>
      {!active && <GameResult game={game} reportPath={reportPath} />}
      {error && <ErrorNotice onRetry={needsSync ? retry : undefined}>{error}</ErrorNotice>}
      {!active && <GameReport game={game} coach={coach} onReview={setRevision} />}
      <div className="play-layout">
        <div className="play-main">
        <GameBoard fen={visibleFEN} color={game.cor_do_jogador} playable={playable}
          legalMoves={game.lances_legais} lastMove={lastMove}
          tip={reviewing ? null : aid.data?.dica || (coachEnabled ? revealedTip(game, coach) : null)}
          visuals={visuals} onIllegal={setError}
          onMove={(preview) => perform("move", (signal) => playApi.mover(id, game.versao, preview.uci, signal), preview)} />
        <GameHistory moves={game.lances} active={active} revision={revision} onReview={setRevision} />
        {coachEnabled && <HintHistory game={game} hints={coach.panel?.dicas} />}
        </div>
        <div className="play-side">
        <GameControls key={game.versao} game={game} active={active} playable={playable} status={status}
          evaluationPoint={score} tip={aid.data?.dica} aidError={aid.error} onRetryAid={aid.retry}
          visuals={visuals} onVisuals={setVisuals}
          onSettings={(settings) => perform("config", (signal) => playApi.configurar(id, { versao: game.versao, ...settings }, signal))}
          onResign={() => perform("end", (signal) => playApi.desistir(id, game.versao, signal))}
          onDraw={(uci) => perform("end", (signal) => playApi.empatar(id, game.versao, uci, signal))} />
        <GameFeedback move={feedback} reviewing={reviewing} disabled={Boolean(pending || game.processando || needsSync)}
          onEvaluate={() => perform("evaluate", (signal) => playApi.avaliar(id, game.versao, feedback.indice, signal))} />
        {coachEnabled && (
          <>
            <GameCoach key={feedback?.indice || "empty"} game={game} move={feedback} coach={coach} reviewing={reviewing} />
            <GameHints key={`hints:${game.versao}`} game={game} playable={playable} coach={coach} />
            <GameChat game={game} canAsk={playable} selectedIndex={reviewedMove?.autor === "jogador" ? reviewedMove.indice : null} />
          </>
        )}
        </div>
      </div>
    </>
  );
}

function usePositionAid(game, playable) {
  const [asked, setAsked] = useState(null);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState(null);
  const id = game?.id;
  const version = game?.versao;
  const showEvaluation = game?.configuracoes.mostrar_avaliacao;
  const recommend = Boolean(game?.configuracoes.mostrar_melhor_lance || (asked !== null && asked === version));
  const key = playable && (showEvaluation || recommend) ? `${version}:${recommend}:${retry}` : null;
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    playApi.posicao(id, version, recommend, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ key, data });
      })
      .catch((err) => {
        if (!controller.signal.aborted) setState({ key, error: err.message });
      });
    return () => controller.abort();
  }, [id, version, recommend, key]);
  const current = key && state?.key === key ? state : null;
  return {
    busy: Boolean(key && recommend && !current),
    data: current?.data,
    error: current?.error,
    ask: () => {
      if (recommend) setRetry((current) => current + 1);
      else setAsked(version);
    },
    retry: () => setRetry((current) => current + 1),
  };
}
