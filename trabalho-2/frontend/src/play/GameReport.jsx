import { useEffect, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Activity, BookOpen, ExternalLink, Lightbulb, Target } from "lucide-react";
import { ClassBadge, ErrorNotice, Loading } from "../components/ChessUi";
import { coachApi } from "../lib/api";
import { BOARD_COLORS, safeTrainingUrl } from "../lib/chess";

const PHASES = { inicio: "Começo", meio: "Meio", fim: "Fim" };
const STATUS = {
  concluida: "Explicação pronta", pendente: "Na fila", em_andamento: "Em preparo",
  ignorada: "Sem comentário", erro: "Falhou", cancelada: "Cancelada",
};

// Relatório com dados reais da partida: classificações, explicações validadas e dicas registradas.
export default function GameReport({ game, coach, onReview }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const explanationState = (coach.panel?.explicacoes || [])
    .map(({ id, status, concluido_em }) => `${id}:${status}:${concluido_em}`).join("|");
  useEffect(() => {
    const controller = new AbortController();
    coachApi.relatorio(game.id, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setReport(data);
        setError("");
      })
      .catch((err) => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [game.id, game.versao, explanationState, retry]);
  useEffect(() => {
    if (report?.status_analise !== "em_andamento") return;
    const timer = setTimeout(() => setRetry((n) => n + 1), 4000);
    return () => clearTimeout(timer);
  }, [report]);
  if (error) return <ErrorNotice onRetry={() => { setError(""); setRetry((n) => n + 1); }}>{error}</ErrorNotice>;
  if (!report) return <Loading>Montando o relatório da partida…</Loading>;
  const stats = report.estatisticas;
  return (
    <section className="panel play-report" aria-labelledby="play-report-title" data-testid="game-report">
      <div className="section-heading">
        <div>
          <span className="eyebrow">RELATÓRIO DA PARTIDA</span>
          <h2 id="play-report-title">O que esta partida ensinou</h2>
        </div>
        <Activity size={21} aria-hidden="true" />
      </div>
      <section className="summary-strip" aria-label="Resumo das classificações">
        <div><b>{stats.precisao == null ? "—" : `${stats.precisao.toFixed(1)}%`}</b><span>Precisão</span></div>
        <div><b className="yellow">{stats.imprecisoes}</b><span>Imprecisões</span></div>
        <div><b className="orange">{stats.erros}</b><span>Erros</span></div>
        <div><b className="red-text">{stats.erros_graves}</b><span>Erros graves</span></div>
      </section>
      <p className="field-hint">
        {report.total_meios_lances} meios-lances · {stats.lances_do_jogador_analisados} de {report.lances_do_jogador} lances
        seus avaliados · {report.dicas_usadas.total} dica(s) usada(s) · {report.explicacoes.qwen3} explicação(ões) do Qwen3
        {report.explicacoes.motor ? ` · ${report.explicacoes.motor} de apoio do Stockfish` : ""}
        {report.explicacoes.pendentes ? ` · ${report.explicacoes.pendentes} ainda na fila` : ""}
      </p>
      <div className="report-columns">
        <div>
          <h3>Lances críticos</h3>
          {!report.lances_criticos.length ? <p className="field-hint">Nenhuma imprecisão ou erro nos lances avaliados.</p> : (
            <ul className="critical-moves">
              {report.lances_criticos.map((item) => (
                <li key={item.indice}>
                  <button className="play-history-move" onClick={() => onReview(item.indice)}
                    aria-label={`Revisar o lance ${item.numero} ${item.san}`}>
                    <b>{item.numero}. {item.san}</b>
                    <ClassBadge value={item.classe} />
                    <span className="field-hint">Melhor: {item.melhor_lance}</span>
                    <span className="field-hint">{STATUS[item.explicacao_status] || "Sem explicação"}{item.tema_label && item.tema_label !== "Outro" ? ` · ${item.tema_label}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3>Dificuldades com evidência</h3>
          <ul className="report-list">{report.dificuldades.map((item) => <li key={item}>{item}</li>)}</ul>
          {!report.dificuldades.length && <p className="field-hint">Sem evidência suficiente para apontar uma dificuldade.</p>}
          {report.temas.length > 0 && (
            <p className="coach-tags">
              {report.temas.map((tema) => (
                <span key={tema.tema} className="theme-tag"><Target size={14} />{tema.tema_label} · {tema.ocorrencias}</span>
              ))}
            </p>
          )}
          <h3>Recomendações de estudo</h3>
          <ul className="report-list">{report.recomendacoes.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      </div>
      {report.evolucao.length > 0 && (
        <div className="table-wrap" role="region" tabIndex={0} aria-label="Evolução durante a partida">
          <table>
            <thead><tr><th>Trecho</th><th>Lances</th><th>Precisão</th><th>Imprecisões</th><th>Erros</th><th>Erros graves</th></tr></thead>
            <tbody>
              {report.evolucao.map((fase) => (
                <tr key={fase.fase}>
                  <td>{PHASES[fase.fase]} ({fase.primeiro_lance}–{fase.ultimo_lance})</td>
                  <td>{fase.lances}</td>
                  <td>{fase.precisao == null ? "—" : `${fase.precisao.toFixed(1)}%`}</td>
                  <td>{fase.imprecisoes}</td><td>{fase.erros}</td><td>{fase.erros_graves}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="field-hint">
        <Lightbulb size={14} aria-hidden="true" /> Dicas: {report.dicas_usadas.nivel_1} objetivo · {report.dicas_usadas.nivel_2} pista ·
        {" "}{report.dicas_usadas.nivel_3} lance revelado.
        {report.partida_analise_id && ` Análise completa: ${report.status_analise === "concluida" ? "pronta" : report.status_analise === "em_andamento" ? "em andamento" : "disponível para iniciar"}.`}
      </p>
      <h3><BookOpen size={17} aria-hidden="true" /> Puzzles relacionados</h3>
      <p className="field-hint">
        {report.puzzles_por_tema ? "Selecionados pelos temas confirmados nesta partida." : "Sem tema confirmado: recomendações gerais pela faixa da dificuldade."}
      </p>
      {report.aviso_puzzles && <div className="notice">{report.aviso_puzzles}</div>}
      <div className="puzzle-grid compact">
        {report.puzzles.slice(0, 3).map((puzzle) => (
          <article className="panel puzzle-card" key={puzzle.id}>
            <div className="puzzle-preview">
              <Chessboard options={{
                id: `play-puzzle-${puzzle.id}`, position: puzzle.fen, allowDragging: false, allowDrawingArrows: false,
                showNotation: false, boardOrientation: puzzle.fen.split(" ")[1] === "b" ? "black" : "white", ...BOARD_COLORS,
              }} />
            </div>
            <div className="puzzle-body">
              <span className="eyebrow">PUZZLE {puzzle.id}</span>
              <h3>{puzzle.temas_label?.join(" · ") || "Treino de tática"}</h3>
              <p>Rating {puzzle.rating}</p>
              {safeTrainingUrl(puzzle.url) && (
                <a className="external-link" href={safeTrainingUrl(puzzle.url)} target="_blank" rel="noreferrer">
                  Treinar na Lichess <ExternalLink size={13} />
                </a>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
