import { useEffect, useRef, useState } from "react";
import { MessageCircle, Send } from "lucide-react";
import { ErrorNotice, Loading } from "../components/ChessUi";
import { coachApi, readCache, writeCache } from "../lib/api";
import { SOURCES } from "./settings";

const SUGGESTIONS = [
  "Por que meu último movimento foi ruim?",
  "Qual é a melhor alternativa?",
  "Minha dama está ameaçada?",
  "Existe alguma oportunidade tática?",
  "Como posso desenvolver melhor minhas peças?",
  "O que significa cravada?",
  "Por que perdi material?",
  "Estou em uma posição favorável?",
  "Qual foi meu maior erro até agora?",
];

function moveLabel(move) {
  return `${move.numero}${move.cor === "white" ? "." : "…"} ${move.san}`;
}

export default function GameChat({ game, canAsk, selectedIndex }) {
  const key = `play:chat:${game.id}`;
  const [messages, setMessages] = useState(() => readCache(key, []));
  const [question, setQuestion] = useState("");
  const [selection, setSelection] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => writeCache(key, messages.slice(-30)), [key, messages]);
  const ended = game.status !== "em_andamento";
  const allowed = (canAsk || ended) && !busy;
  const playerMoves = game.lances.filter((move) => move.autor === "jogador");
  const selected = playerMoves.find((move) => move.indice === (selection ?? selectedIndex));
  const positionMove = selected || game.lances.at(-1);
  const label = positionMove ? `posição após ${moveLabel(positionMove)}` : "posição inicial";
  const fen = selected?.fen_depois ?? game.fen;

  async function send(text) {
    const pergunta = text.trim();
    if (!pergunta || !allowed || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const versao = game.versao;
    const indice = (selected || playerMoves.at(-1))?.indice ?? null;
    setBusy(true);
    setError("");
    try {
      const historico = messages.filter((m) => m.fen === fen && m.indice === indice && m.validada !== false).slice(-12)
        .map(({ role, content }) => ({ role, content: content.slice(0, 2000) }));
      const body = { pergunta, versao, historico,
        ...(selected ? { indice, posicao: "apos_lance" } : {}) };
      const result = await coachApi.chat(game.id, body, controller.signal);
      if (controller.signal.aborted) return;
      if (result.jogo_id !== game.id || result.versao !== versao || result.fen !== fen || result.indice !== indice) {
        throw new Error("O contexto da resposta não corresponde à posição da pergunta.");
      }
      const validada = result.validada && result.status !== "indisponivel";
      setMessages((items) => [
        ...items,
        { role: "user", content: pergunta, label, fen, indice, validada },
        { role: "assistant", content: result.resposta, validada, fonte: result.fonte, label, fen, indice,
          lance: result.lance, versao: result.versao, segundos: result.duracao_ms / 1000,
          tools: result.ferramentas_usadas.map((tool) => tool.nome) },
      ]);
      setQuestion("");
    } catch (err) {
      if (!controller.signal.aborted) setError(err.status === 409 ? "A posição mudou. Faça a pergunta de novo sobre o lance atual." : err.message);
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section className="panel chat-panel play-chat" aria-labelledby="play-chat-title" data-testid="game-chat">
      <div className="section-heading">
        <h2 id="play-chat-title"><MessageCircle size={19} aria-hidden="true" /> Pergunte ao treinador</h2>
        <span className="field-hint">{label} · versão {game.versao}</span>
      </div>
      {playerMoves.length > 0 && (
        <div className="mode-switch">
          <label htmlFor="play-chat-position">Posição da pergunta</label>
          <select id="play-chat-position" value={selected?.indice ?? 0}
            onChange={(event) => setSelection(Number(event.target.value))}>
            <option value={0}>Posição atual</option>
            {playerMoves.slice().reverse().map((move) => (
              <option key={move.id} value={move.indice}>Após {moveLabel(move)}</option>
            ))}
          </select>
        </div>
      )}
      <div className="chat-messages" aria-live="polite" role="log">
        {!messages.length && (
          <p className="chat-intro">
            As respostas usam a posição confirmada no servidor e o histórico desta partida. Cada resposta indica a
            posição a que se refere.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-message ${m.role}`}>
            <strong>{m.role === "user" ? "Você" : "Treinador"}</strong>
            <p>{m.content.replace(/`/g, "")}</p>
            {m.role === "assistant" && (
              <small>
                {m.fonte === "qwen3" && !m.tools?.includes("buscar_conceitos") ? "Qwen3 · validado" : SOURCES[m.fonte] || ""}
                {` · ${m.label}`}{Number.isFinite(m.segundos) ? ` · ${m.segundos.toFixed(1)} s` : ""}
              </small>
            )}
          </div>
        ))}
        {busy && <Loading>O treinador está consultando a posição…</Loading>}
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <div className="chat-suggestions" role="group" aria-label="Perguntas sugeridas">
        {SUGGESTIONS.map((item) => (
          <button key={item} type="button" className="chip" disabled={!allowed} onClick={() => send(item)}>{item}</button>
        ))}
      </div>
      <form className="chat-form" onSubmit={(event) => { event.preventDefault(); send(question); }}>
        <label htmlFor="play-question" className="sr-only">Pergunta sobre a partida</label>
        <input id="play-question" value={question} onChange={(event) => setQuestion(event.target.value)}
          maxLength={2000} placeholder={allowed || busy ? "Pergunte sobre a posição ou a partida" : "Aguarde o Stockfish jogar"}
          disabled={!allowed} />
        <button className="icon-button" type="submit" aria-label="Enviar pergunta" title="Enviar pergunta"
          disabled={!allowed || !question.trim()}>
          <Send size={18} />
        </button>
      </form>
    </section>
  );
}
