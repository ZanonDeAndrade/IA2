import { useEffect, useRef, useState } from "react";
import { Play, Swords } from "lucide-react";
import { ErrorNotice, Loading } from "../components/ChessUi";
import { playApi, readCache, writeCache } from "../lib/api";
import { COLORS, DEFAULT_SETTINGS, LEVELS, MODES, playPath } from "./settings";

function randomHex(bytes) {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export default function GameSetup() {
  const [settings, setSettings] = useState(() => ({ ...DEFAULT_SETTINGS, ...readCache("play:settings") }));
  const [resume] = useState(() => readCache("play:active"));
  const [session] = useState(() => readCache("play:session"));
  const [matches, setMatches] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    playApi.listar(session, controller.signal)
      .then(({ partidas }) => {
        if (!controller.signal.aborted) setMatches(partidas.filter((game) => game.id !== resume));
      })
      .catch((err) => {
        if (!controller.signal.aborted) setHistoryError(err.message);
      });
    return () => controller.abort();
  }, [session, resume]);
  const automaticRequired = settings.modo_treinador && settings.modo_assistencia !== "livre";

  function update(name, value) {
    setSettings((current) => ({ ...current, [name]: value }));
  }

  async function start(event) {
    event.preventDefault();
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const token = readCache("play:session") || randomHex(32);
      writeCache("play:session", token);
      const game = await playApi.iniciar(settings, controller.signal, token);
      if (controller.signal.aborted) return;
      writeCache("play:profile", game.usuario);
      writeCache("play:settings", settings);
      writeCache("play:active", game.id);
      window.location.hash = playPath(game.id);
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message);
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Jogar contra IA<span className="accent">.</span></h1>
          <p>Jogue contra o Stockfish e receba feedback sobre seus lances.</p>
        </div>
        <Swords className="heading-icon" size={36} aria-hidden="true" />
      </div>
      <form className="panel play-setup" onSubmit={start}>
        <div className="section-heading">
          <h2>Configurar partida</h2>
          {resume && <a className="text-button" href={playPath(resume)}>Retomar partida</a>}
        </div>
        <fieldset disabled={busy} className="play-setup-fields">
          <div>
            <label htmlFor="play-color">Cor das peças</label>
            <select id="play-color" value={settings.cor_do_jogador}
              onChange={(event) => update("cor_do_jogador", event.target.value)}>
              {Object.entries(COLORS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              <option value="random">Aleatória</option>
            </select>
          </div>
          <div>
            <label htmlFor="play-level">Dificuldade</label>
            <select id="play-level" value={settings.dificuldade}
              onChange={(event) => update("dificuldade", event.target.value)}>
              {Object.entries(LEVELS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </div>
          <label className="play-toggle">
            <input type="checkbox" checked={settings.modo_treinador}
              onChange={(event) => update("modo_treinador", event.target.checked)} />
            Ativar treinador
          </label>
          {settings.modo_treinador && <fieldset className="coach-modes" aria-describedby="coach-modes-note">
            <legend>Assistência do treinador</legend>
            {Object.entries(MODES).map(([id, mode]) => (
              <label key={id} className={`coach-mode ${settings.modo_assistencia === id ? "selected" : ""}`}>
                <input type="radio" name="modo_assistencia" value={id} checked={settings.modo_assistencia === id}
                  onChange={() => update("modo_assistencia", id)} />
                <span>
                  <b>{mode.label}</b>
                  <small>{mode.description}</small>
                </span>
              </label>
            ))}
            <p id="coach-modes-note" className="field-hint">
              O Stockfish joga e avalia. O Qwen3 explica em segundo plano: você nunca espera a explicação para jogar.
              Dá para mudar o modo durante a partida.
            </p>
          </fieldset>}
          <div className="play-assistance">
            <label className="play-toggle">
              <input type="checkbox" checked={automaticRequired || settings.analise_automatica}
                disabled={automaticRequired}
                onChange={(event) => update("analise_automatica", event.target.checked)} />
              Avaliar meus lances automaticamente
            </label>
            {settings.modo_treinador && settings.modo_assistencia === "intensivo" && (
              <label className="play-toggle">
                <input type="checkbox" checked={settings.revelar_alternativa}
                  onChange={(event) => update("revelar_alternativa", event.target.checked)} />
                Mostrar a melhor alternativa nos comentários
              </label>
            )}
            <label htmlFor="play-assistance-option">Auxílio durante a partida</label>
            <select id="play-assistance-option" value={String(settings.mostrar_melhor_lance)}
              aria-describedby={settings.modo_treinador ? "play-assistance-note" : undefined}
              onChange={(event) => update("mostrar_melhor_lance", event.target.value === "true")}>
              <option value="false">Ocultar o melhor lance</option>
              <option value="true">Mostrar sempre o melhor lance</option>
            </select>
            {settings.modo_treinador && (
              <p id="play-assistance-note" className="field-hint">As dicas em etapas revelam o lance só no último passo.</p>
            )}
            <label className="play-toggle">
              <input type="checkbox" checked={settings.mostrar_avaliacao}
                onChange={(event) => update("mostrar_avaliacao", event.target.checked)} />
              Mostrar avaliação
            </label>
          </div>
        </fieldset>
        {error && <ErrorNotice>{error}</ErrorNotice>}
        <button className="button primary" disabled={busy}>
          <Play size={17} aria-hidden="true" /> Iniciar partida
        </button>
        {busy && <Loading>Preparando a partida…</Loading>}
      </form>
      {(matches.length > 0 || historyError) && (
        <section className="panel play-setup play-saved" aria-labelledby="play-saved-title">
          <h2 id="play-saved-title">Partidas recentes</h2>
          {historyError && <ErrorNotice>{historyError}</ErrorNotice>}
          <ul>
            {matches.map((game) => (
              <li key={game.id}>
                <a className="text-button" href={playPath(game.id)}>
                  {new Date(game.criado_em).toLocaleString("pt-BR")} · {LEVELS[game.dificuldade]} · {COLORS[game.cor_do_jogador]}
                  {game.status === "em_andamento" ? " · Em andamento" : ` · ${game.resultado}`}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
