import { useEffect, useRef, useState } from "react";
import { Chessboard } from "react-chessboard";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  ArrowDownToLine,
  BookOpen,
  ChartNoAxesCombined,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CircleAlert,
  Copy,
  ExternalLink,
  Flag,
  FlipVertical2,
  FolderOpen,
  House,
  LoaderCircle,
  MessageCircle,
  Moon,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  Sun,
  Swords,
  Target,
  Trophy,
  X,
} from "lucide-react";
import { api, readCache, request, writeCache } from "./lib/api";
import {
  arrow,
  CLASSES,
  dateLabel,
  evaluation,
  INITIAL_FEN,
  moveUci,
  safeTrainingUrl,
} from "./lib/chess";
import { demoGame, demoReport } from "./lib/demo";
import "./App.css";
import "./glass.css";

const go = (path) => {
  window.location.hash = path;
};
const decode = (value) => {
  try {
    return decodeURIComponent(value || "");
  } catch {
    return "";
  }
};
function useRoute() {
  const [route, setRoute] = useState(window.location.hash.slice(1) || "/");
  useEffect(() => {
    const update = () => setRoute(window.location.hash.slice(1) || "/");
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
function IconButton({ label, children, ...props }) {
  return (
    <button
      className="icon-button"
      type="button"
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </button>
  );
}
function Empty({ icon: Icon = FolderOpen, title, children }) {
  return (
    <div className="empty">
      <Icon size={32} strokeWidth={1.4} />
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
function ErrorNotice({ children, onRetry }) {
  return (
    <div className="notice error" role="alert">
      <CircleAlert size={19} />
      <div>{children}</div>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          Tentar novamente
        </button>
      )}
    </div>
  );
}
function Loading({ children = "Carregando…" }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} />
      {children}
    </div>
  );
}
function ClassBadge({ value }) {
  const c = CLASSES[value] || CLASSES.aceitavel;
  return (
    <span className={`badge class-${value}`}>
      <b>{c.symbol}</b>
      {c.label}
    </span>
  );
}
function ToolList({ tools = [] }) {
  return (
    tools.length > 0 && (
      <div className="tools">
        <ShieldCheck size={14} />
        <span>
          Ferramentas:{" "}
          {tools.map((t) => (typeof t === "string" ? t : t.nome)).join(" · ")}
        </span>
      </div>
    )
  );
}
function download(name, content, type = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const route = useRoute();
  const [theme, setTheme] = useState(() => readCache("theme", "dark"));
  const [health, setHealth] = useState("checking");
  const [games, setGames] = useState(() => readCache("games", []));
  const [user, setUser] = useState(() => readCache("user", ""));
  const isDemo = route.startsWith("/demo");
  const page = route.includes("/analise/")
    ? "analise"
    : route.includes("/relatorio")
      ? "relatorio"
      : "inicio";
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writeCache("theme", theme);
  }, [theme]);
  useEffect(() => {
    const c = new AbortController();
    const check = () =>
      request("/healthz", { signal: c.signal, timeout: 5000 })
        .then(() => setHealth("online"))
        .catch(() => {
          if (!c.signal.aborted) setHealth("offline");
        });
    check();
    const timer = setInterval(check, 30000);
    return () => {
      c.abort();
      clearInterval(timer);
    };
  }, []);
  function saveGames(items, usuario) {
    setGames(items);
    writeCache("games", items);
    if (usuario) {
      setUser(usuario);
      writeCache("user", usuario);
    }
  }
  const reportPath = isDemo
    ? "/demo/relatorio"
    : `/relatorio/${encodeURIComponent(user)}`;
  useEffect(() => {
    window.scrollTo(0, 0);
    document.title = `${page === "inicio" ? "Minhas partidas" : page === "analise" ? "Análise da partida" : "Meu progresso"} · Lance a Lance`;
  }, [route, page]);
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Pular para o conteúdo
      </a>
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="Lance a Lance, início">
          <span className="brand-mark">♞</span>
          <span>
            Lance
            <span className="brand-small">
              a Lance<span className="brand-dot">.</span>
            </span>
          </span>
        </a>
        <nav aria-label="Navegação principal">
          <a className={page === "inicio" ? "active" : ""} href="#/">
            <House size={19} />
            Minhas partidas
          </a>
          <a
            className={page === "analise" ? "active" : ""}
            href={
              isDemo
                ? "#/demo/analise/demo"
                : games[0]
                  ? `#/analise/${games[0].id}`
                  : "#/"
            }
          >
            <Swords size={19} />
            Análise da partida
          </a>
          <a
            className={page === "relatorio" ? "active" : ""}
            href={`#${reportPath}`}
          >
            <ChartNoAxesCombined size={19} />
            Meu progresso
          </a>
        </nav>
        <button
          onClick={() => go("/demo/analise/demo")}
          className="demo-shortcut"
        >
          <Play size={17} />
          Explorar demonstração
        </button>
        <div className="sidebar-footer">
          <div className="engine-label">
            <span className={`status-dot ${health}`} />
            {health === "online"
              ? "Servidor conectado"
              : health === "checking"
                ? "Conectando ao servidor"
                : "Servidor desconectado"}
          </div>
          <p>Stockfish + IA · português</p>
          <button
            className="theme-button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}Modo{" "}
            {theme === "dark" ? "claro" : "escuro"}
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Seu espaço de treino <span>/</span>{" "}
            <b>
              {page === "inicio"
                ? "Minhas partidas"
                : page === "analise"
                  ? "Análise"
                  : "Meu progresso"}
            </b>
          </div>
          <div className="topbar-right">
            <span className="grounded">
              <ShieldCheck size={15} />
              Lances verificados
            </span>
            <span className="avatar">{(user || "X")[0].toUpperCase()}</span>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {isDemo && (
            <div className="notice demo-notice">
              <Play size={17} />
              <div>
                <strong>Demonstração offline.</strong> Exemplo didático com
                dados ilustrativos. Nenhuma resposta de IA está sendo gerada.
              </div>
              <button className="text-button" onClick={() => go("/")}>
                Sair da demo
              </button>
            </div>
          )}
          {page === "inicio" && (
            <Home
              games={games}
              user={user}
              onImport={saveGames}
              health={health}
            />
          )}
          {page === "analise" && (
            <Analysis
              key={`${isDemo}:${route}`}
              id={decode(route.split("/").at(-1))}
              demo={isDemo}
              onGameUpdate={(game) => {
                const updated = games.map((g) =>
                  g.id === game.id
                    ? {
                        ...g,
                        status_analise: game.status_analise,
                        erros_graves: game.resumo?.erros_graves || 0,
                      }
                    : g,
                );
                setGames(updated);
                writeCache("games", updated);
              }}
            />
          )}
          {page === "relatorio" && (
            <Report
              key={`${isDemo}:${route}`}
              user={decode(route.split("/")[2]) || user}
              demo={isDemo}
              onUser={(value) => {
                setUser(value);
                writeCache("user", value);
                go(`/relatorio/${encodeURIComponent(value)}`);
              }}
            />
          )}
        </main>
        <footer className="page-footer">
          <span>Um lance de cada vez.</span>
          <span>Lance a Lance · IA II</span>
        </footer>
      </div>
    </div>
  );
}

function Home({ games, user, onImport, health }) {
  const [mode, setMode] = useState("usuario");
  const [username, setUsername] = useState(user);
  const [quantity, setQuantity] = useState(10);
  const [rhythm, setRhythm] = useState("");
  const [pgn, setPgn] = useState("");
  const [color, setColor] = useState("white");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    try {
      const body =
        mode === "usuario"
          ? {
              usuario: username.trim(),
              max: Number(quantity),
              ...(rhythm ? { ritmo: rhythm } : {}),
            }
          : {
              pgn: pgn.trim(),
              cor_do_jogador: color,
              ...(username.trim() ? { usuario: username.trim() } : {}),
            };
      const result = await api.importar(body, c.signal);
      const merged = [
        ...result.partidas,
        ...games.filter((g) => !result.partidas.some((p) => p.id === g.id)),
      ].slice(0, 50);
      onImport(merged, result.usuario);
      if (mode === "pgn" && result.partidas[0])
        go(`/analise/${result.partidas[0].id}`);
    } catch (e) {
      if (!c.signal.aborted) setError(e.message);
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">SEU ESPAÇO DE TREINO</span>
          <h1>
            Seu próximo melhor lance<span className="accent">.</span>
          </h1>
          <p>Importe uma partida e descubra onde seu jogo pode evoluir.</p>
        </div>
      </div>
      <div className="home-grid">
        <section className="panel import-panel" aria-labelledby="import-title">
          <div className="section-heading">
            <div>
              <h2 id="import-title">Importar partida</h2>
            </div>
          </div>
          <div
            className="segmented"
            role="group"
            aria-label="Origem da partida"
          >
            <button
              aria-pressed={mode === "usuario"}
              onClick={() => {
                setMode("usuario");
                setError("");
              }}
            >
              Chess.com
            </button>
            <button
              aria-pressed={mode === "pgn"}
              onClick={() => {
                setMode("pgn");
                setError("");
              }}
            >
              Colar PGN
            </button>
          </div>
          <form onSubmit={submit}>
            <label htmlFor="username">
              {mode === "usuario"
                ? "Seu usuário no Chess.com"
                : "Identificador do jogador (opcional)"}
            </label>
            <input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Ex.: seu_nome_de_usuario"
              pattern="[a-zA-Z0-9_-]{1,50}"
              maxLength={50}
              required={mode === "usuario"}
              autoComplete="username"
            />
            {mode === "usuario" ? (
              <div className="form-row">
                <div>
                  <label htmlFor="quantity">Quantidade de partidas</label>
                  <select
                    id="quantity"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                  >
                    {[1, 5, 10, 20, 50].map((n) => (
                      <option key={n} value={n}>
                        {n} {n === 1 ? "partida" : "partidas"}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="rhythm">Ritmo</label>
                  <select
                    id="rhythm"
                    value={rhythm}
                    onChange={(e) => setRhythm(e.target.value)}
                  >
                    <option value="">Todos os ritmos</option>
                    <option value="bullet">Bullet</option>
                    <option value="blitz">Blitz</option>
                    <option value="rapid">Rápida</option>
                    <option value="daily">Diária</option>
                  </select>
                </div>
              </div>
            ) : (
              <>
                <label htmlFor="pgn">Partida em PGN</label>
                <textarea
                  id="pgn"
                  value={pgn}
                  onChange={(e) => setPgn(e.target.value)}
                  required
                  maxLength={256000}
                  rows={5}
                  placeholder={
                    '[White "Jogador"]\n[Black "Adversário"]\n\n1. e4 e5 2. Nf3 Nc6…'
                  }
                />
                <label htmlFor="color">Sua cor na partida</label>
                <select
                  id="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                >
                  <option value="white">Brancas</option>
                  <option value="black">Pretas</option>
                </select>
              </>
            )}
            {error && <ErrorNotice>{error}</ErrorNotice>}
            <button className="button primary full-width" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <ArrowDownToLine size={18} />
              )}{" "}
              {busy ? "Importando partidas…" : "Importar partidas"}
            </button>
            <p className="field-hint">
              {mode === "usuario"
                ? "Apenas partidas públicas. Não precisamos da sua senha."
                : "Cole uma partida por vez. O identificador agrupa suas partidas no relatório."}
            </p>
          </form>
        </section>
        <section className="intro-card">
          <div className="mini-board" aria-hidden="true">
            {Array.from({ length: 16 }, (_, i) => (
              <span
                key={i}
                className={(Math.floor(i / 4) + i) % 2 ? "dark" : "light"}
              >
                {{ 2: "♚", 6: "♟", 9: "♘", 12: "♔" }[i]}
              </span>
            ))}
          </div>
          <h2>Entenda cada jogada.</h2>
          <p>
            Explore uma análise guiada e veja como transformar um erro em
            aprendizado.
          </p>
          <button
            className="button secondary"
            onClick={() => go("/demo/analise/demo")}
          >
            <Play size={17} />
            Experimentar uma análise
          </button>
          <span className="field-hint">
            Demonstração disponível sem conexão
          </span>
        </section>
      </div>
      <section className="games-section" aria-labelledby="games-title">
        <div className="section-heading">
          <div>
            <h2 id="games-title">
              Minhas partidas <span className="count">{games.length}</span>
            </h2>
          </div>
          {user && (
            <a
              className="button secondary"
              href={`#/relatorio/${encodeURIComponent(user)}`}
            >
              <Activity size={17} />
              Ver meu progresso
            </a>
          )}
        </div>
        {!games.length ? (
          <div className="panel">
            <Empty title="Sua próxima descoberta começa aqui">
              Importe suas partidas ou explore a demonstração para conhecer o
              treinador.
            </Empty>
          </div>
        ) : (
          <div className="panel game-list">
            {games.map((game) => (
              <div className="game-row" key={game.id}>
                <span className="game-icon">
                  <Swords size={22} />
                </span>
                <div className="game-info">
                  <h3>vs. {game.adversario || "Adversário"}</h3>
                  <p>{game.abertura || "Abertura não informada"}</p>
                  <span className="mobile-meta">
                    {dateLabel(game.data)} · {game.resultado}
                  </span>
                </div>
                <div className="game-meta">
                  <b>{game.resultado}</b>
                  <span>{dateLabel(game.data)}</span>
                </div>
                <div className="game-status">
                  <span>
                    {game.status_analise === "concluida"
                      ? "Analisada"
                      : game.status_analise === "em_andamento"
                        ? "Em análise"
                        : game.status_analise === "erro"
                          ? "Análise interrompida"
                          : "Pronta para analisar"}
                  </span>
                  {game.status_analise === "concluida" && (
                    <small>{game.erros_graves || 0} erros graves</small>
                  )}
                </div>
                <a className="button secondary" href={`#/analise/${game.id}`}>
                  Abrir análise
                </a>
              </div>
            ))}
          </div>
        )}
        {health === "offline" && (
          <p className="field-hint connection-hint">
            O servidor está desconectado. A demonstração continua disponível;
            partidas já abertas podem ser consultadas pelo cache deste
            navegador.
          </p>
        )}
      </section>
    </>
  );
}

function Analysis({ id, demo, onGameUpdate }) {
  const [game, setGame] = useState(demo ? demoGame : null);
  const [busy, setBusy] = useState(!demo);
  const [error, setError] = useState("");
  const [task, setTask] = useState(null);
  const [offline, setOffline] = useState(false);
  const [retry, setRetry] = useState(0);
  const [index, setIndex] = useState(demo ? 3 : 0);
  const [before, setBefore] = useState(true);
  const [flipped, setFlipped] = useState(false);
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [copied, setCopied] = useState(false);
  const controller = useRef(null);
  const polling = useRef(null);
  const gameUpdate = useRef(onGameUpdate);
  gameUpdate.current = onGameUpdate;
  function saveGame(data) {
    setGame(data);
    writeCache(`game:${id}`, { data, savedAt: new Date().toISOString() });
    gameUpdate.current(data);
  }
  useEffect(() => {
    if (demo) return;
    const c = new AbortController();
    controller.current = c;
    setBusy(true);
    setError("");
    setOffline(false);
    api
      .partida(id, c.signal)
      .then((data) => {
        if (!c.signal.aborted) saveGame(data);
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setError(e.message);
          const cached = readCache(`game:${id}`);
          if (cached?.data) {
            setGame(cached.data);
            setOffline(cached.savedAt);
          }
        }
      })
      .finally(() => {
        if (!c.signal.aborted) setBusy(false);
      });
    return () => {
      c.abort();
      controller.current?.abort();
      clearTimeout(polling.current);
    };
  }, [id, demo, retry]); // Cada rota mantém seu próprio controlador de requisições.
  async function startAnalysis() {
    setBusy(true);
    setError("");
    setTask(null);
    setOffline(false);
    controller.current?.abort();
    clearTimeout(polling.current);
    const c = new AbortController();
    controller.current = c;
    try {
      const started = await api.analisar(id, c.signal);
      async function poll() {
        try {
          const progress = await api.tarefa(started.tarefa_id, c.signal);
          if (c.signal.aborted) return;
          setTask(progress);
          if (progress.status === "erro")
            throw new Error(
              progress.erro || "A análise foi interrompida. Tente novamente.",
            );
          const data = await api.partida(id, c.signal);
          if (c.signal.aborted) return;
          saveGame(data);
          if (progress.status === "concluida") {
            setBusy(false);
            setIndex(0);
            return;
          }
          polling.current = setTimeout(poll, 2000);
        } catch (e) {
          if (!c.signal.aborted) {
            setError(e.message);
            setBusy(false);
          }
        }
      }
      await poll();
    } catch (e) {
      if (!c.signal.aborted) {
        setError(e.message);
        setBusy(false);
      }
    }
  }
  const moves = game?.lances || [];
  const move = moves.find((m) => m.indice === index);
  const fen = move
    ? before
      ? move.fen_antes
      : move.fen_depois
    : game?.fen_inicial || INITIAL_FEN;
  const orientation = flipped
    ? game?.cor_do_jogador === "black"
      ? "white"
      : "black"
    : game?.cor_do_jogador || "white";
  function selectMove(value) {
    setIndex(Math.max(0, Math.min(moves.at(-1)?.indice || 0, value)));
    setBefore(true);
  }
  useEffect(() => {
    const handler = (event) => {
      if (
        ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(
          event.target.tagName,
        ) ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey
      )
        return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        selectMove(index + (event.key === "ArrowRight" ? 1 : -1));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [index, moves]);
  if (!game)
    return (
      <>
        <div className="page-heading">
          <div>
            <span className="eyebrow">REVISÃO DA PARTIDA</span>
            <h1>Análise da partida</h1>
          </div>
        </div>
        {busy ? (
          <Loading>Buscando sua partida…</Loading>
        ) : (
          <ErrorNotice onRetry={() => setRetry((n) => n + 1)}>
            {error || "Partida não encontrada."}
          </ErrorNotice>
        )}
      </>
    );
  const arrows =
    move && before
      ? [
          arrow(move.uci || moveUci(fen, move.san), "#ed626dcc"),
          arrow(
            move.melhor_lance_uci || moveUci(fen, move.melhor_lance),
            "#42ba9acc",
          ),
        ].filter(Boolean)
      : [];
  const topColor = orientation === "white" ? "black" : "white";
  const bottomColor = orientation;
  const shownMoves = onlyErrors
    ? moves.filter((m) => m.classe === "erro" || m.classe === "erro_grave")
    : moves;
  return (
    <>
      <div className="page-heading compact">
        <div>
          <span className="eyebrow">CADA POSIÇÃO, UMA NOVA DESCOBERTA</span>
          <h1>
            {game.jogadores?.white?.nome || "Brancas"}{" "}
            <span className="versus">vs.</span>{" "}
            {game.jogadores?.black?.nome || "Pretas"}
          </h1>
          <p>
            {game.abertura || "Revisão da partida"}{" "}
            <span className="separator">·</span> {dateLabel(game.data)}{" "}
            <span className="separator">·</span> {game.resultado}
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => download("lance-a-lance.pgn", game.pgn)}
        >
          <ArrowDownToLine size={16} />
          Baixar PGN
        </button>
      </div>
      {error && (
        <ErrorNotice onRetry={() => setRetry((n) => n + 1)}>
          {error}
        </ErrorNotice>
      )}
      {offline && (
        <div className="notice">
          <FolderOpen size={18} />
          <span>
            Exibindo a última versão salva neste navegador em{" "}
            {new Date(offline).toLocaleString("pt-BR")}. Chat e novas
            explicações precisam do servidor.
          </span>
        </div>
      )}
      {!demo && game.status_analise !== "concluida" && !busy && (
        <div className="analysis-callout">
          <div>
            <h3>Vamos encontrar os momentos importantes?</h3>
            <p>
              O motor analisa os lances; depois você pode pedir uma explicação
              para cada posição.
            </p>
          </div>
          <button className="button primary" onClick={startAnalysis}>
            <Play size={17} />
            {moves.length ? "Retomar análise" : "Analisar partida"}
          </button>
        </div>
      )}
      {busy && (
        <div className="panel progress-panel" role="status">
          <div>
            <span>
              <LoaderCircle className="spin" size={17} />{" "}
              {task ? "Analisando sua partida" : "Preparando análise…"}
            </span>
            <b>{Math.round(task?.progresso?.percentual || 0)}%</b>
          </div>
          <progress value={task?.progresso?.percentual || 0} max={100} />
          <p>
            {task
              ? `${task.progresso.lance_atual} de ${task.progresso.total_lances} meios-lances · você já pode explorar os lances disponíveis.`
              : "A análise pode levar cerca de um minuto."}
          </p>
        </div>
      )}
      <div className="analysis-grid">
        <section className="board-column" aria-label="Tabuleiro e avaliação">
          <Player player={game.jogadores?.[topColor]} color={topColor} />
          <div className="board-frame">
            <Chessboard
              options={{
                id: "analysis-board",
                position: fen,
                boardOrientation: orientation,
                allowDragging: false,
                allowDrawingArrows: false,
                arrows,
                darkSquareStyle: { backgroundColor: "#52766a" },
                lightSquareStyle: { backgroundColor: "#e0e7df" },
                animationDurationInMs: 180,
              }}
            />
          </div>
          <Player player={game.jogadores?.[bottomColor]} color={bottomColor} />
          <div className="board-toolbar">
            <div className="navigation-controls">
              <IconButton
                label="Posição inicial"
                onClick={() => selectMove(0)}
                disabled={index === 0}
              >
                <ChevronsLeft size={19} />
              </IconButton>
              <IconButton
                label="Lance anterior"
                onClick={() => selectMove(index - 1)}
                disabled={index === 0}
              >
                <ChevronLeft size={21} />
              </IconButton>
              <span aria-live="polite">
                {move
                  ? `${move.numero}${move.cor === "black" ? "…" : "."} ${move.san}`
                  : "Início"}
              </span>
              <IconButton
                label="Próximo lance"
                onClick={() => selectMove(index + 1)}
                disabled={index >= (moves.at(-1)?.indice || 0)}
              >
                <ChevronRight size={21} />
              </IconButton>
              <IconButton
                label="Último lance"
                onClick={() => selectMove(moves.at(-1)?.indice || 0)}
                disabled={index >= (moves.at(-1)?.indice || 0)}
              >
                <ChevronsRight size={19} />
              </IconButton>
            </div>
            <IconButton
              label="Virar tabuleiro"
              onClick={() => setFlipped(!flipped)}
            >
              <FlipVertical2 size={18} />
            </IconButton>
          </div>
          {move && (
            <div className="position-mode">
              <button aria-pressed={before} onClick={() => setBefore(true)}>
                Antes do lance
              </button>
              <button aria-pressed={!before} onClick={() => setBefore(false)}>
                Depois do lance
              </button>
            </div>
          )}
          <div className="board-legend">
            <span>
              <i className="legend-line red" />
              Lance jogado
            </span>
            <span>
              <i className="legend-line green" />
              Melhor lance
            </span>
            <button
              className="text-button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(fen);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                } catch {
                  setError(
                    "Não foi possível copiar. Verifique a permissão da área de transferência.",
                  );
                }
              }}
            >
              <Copy size={13} />
              {copied ? "FEN copiado" : "Copiar FEN"}
            </button>
          </div>
          <section className="panel chart-panel">
            <div className="section-heading">
              <h3>A história da partida</h3>
              <span className="field-hint">Perspectiva das brancas</span>
            </div>
            <EvaluationChart
              points={game.curva_avaliacao || []}
              onSelect={selectMove}
            />
            <div className="chart-caption">
              <span>Vantagem das brancas ↑ · pretas ↓</span>
              <span>
                {evaluation(
                  game.curva_avaliacao?.find((p) => p.lance === index),
                )}
              </span>
            </div>
          </section>
        </section>
        <div className="review-column">
          <section className="summary-strip" aria-label="Resumo da partida">
            <div>
              <b>
                {game.resumo?.precisao == null
                  ? "—"
                  : `${game.resumo.precisao.toFixed(1)}%`}
              </b>
              <span>Precisão</span>
            </div>
            <div>
              <b className="yellow">{game.resumo?.imprecisoes || 0}</b>
              <span>Imprecisões</span>
            </div>
            <div>
              <b className="orange">{game.resumo?.erros || 0}</b>
              <span>Erros</span>
            </div>
            <div>
              <b className="red-text">{game.resumo?.erros_graves || 0}</b>
              <span>Erros graves</span>
            </div>
          </section>
          <section className="panel moves-panel">
            <div className="section-heading">
              <h2>Lance a lance</h2>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={onlyErrors}
                  onChange={(e) => setOnlyErrors(e.target.checked)}
                />
                Só erros
              </label>
            </div>
            {!shownMoves.length ? (
              <p className="small-empty">
                {onlyErrors
                  ? "Nenhum erro encontrado nos lances disponíveis."
                  : "Inicie a análise para explorar seus lances."}
              </p>
            ) : (
              <div
                className="moves-grid"
                role="group"
                aria-label="Lances da partida"
              >
                {shownMoves.map((m) => (
                  <button
                    key={m.indice}
                    className={`move class-${m.classe} ${index === m.indice ? "selected" : ""}`}
                    onClick={() => selectMove(m.indice)}
                    aria-pressed={index === m.indice}
                    aria-label={`${m.numero}${m.cor === "black" ? " pretas" : " brancas"}, ${m.san}, ${CLASSES[m.classe]?.label}`}
                  >
                    <span>
                      {m.numero}
                      {m.cor === "black" ? "…" : "."}
                    </span>
                    <b>{m.san}</b>
                    <em title={CLASSES[m.classe]?.label}>
                      {CLASSES[m.classe]?.symbol}
                    </em>
                  </button>
                ))}
              </div>
            )}
          </section>
          <Explanation
            key={`${id}:${move?.indice || 0}`}
            move={move}
            demo={demo}
            disabled={!!offline}
            onSave={(exp) => {
              const data = {
                ...game,
                lances: game.lances.map((m) =>
                  m.indice === move.indice ? { ...m, explicacao: exp } : m,
                ),
              };
              if (demo) setGame(data);
              else saveGame(data);
            }}
          />
          <Chat key={fen} fen={fen} demo={demo} disabled={!!offline} />
        </div>
      </div>
      <div className="analysis-bottom">
        <p>
          <ShieldCheck size={16} />O motor calcula. A IA explica. Você aprende.
        </p>
        <a
          className="button secondary"
          href={
            demo
              ? "#/demo/relatorio"
              : `#/relatorio/${encodeURIComponent(game.usuario || "")}`
          }
        >
          <ChartNoAxesCombined size={17} />
          Ver meu progresso
        </a>
      </div>
    </>
  );
}

function Player({ player, color }) {
  return (
    <div className="player">
      <span className={`piece-avatar ${color}`}>
        {color === "white" ? "♔" : "♚"}
      </span>
      <b>{player?.nome || (color === "white" ? "Brancas" : "Pretas")}</b>
      <span>{player?.rating || "Sem rating"}</span>
      <span className="player-color">
        {color === "white" ? "Brancas" : "Pretas"}
      </span>
    </div>
  );
}

function EvaluationChart({ points, onSelect }) {
  if (!points.length)
    return (
      <div className="small-empty">
        A avaliação aparecerá conforme a análise avançar.
      </div>
    );
  const data = points.map((p) => ({
    ...p,
    value:
      p.avaliacao?.tipo === "mate"
        ? p.avaliacao.a_favor
          ? 10
          : -10
        : Math.max(-10, Math.min(10, (p.cp ?? p.avaliacao?.valor ?? 0) / 100)),
  }));
  return (
    <>
      <div
        className="eval-chart"
        role="img"
        aria-label="Avaliação ao longo da partida; use também os botões de lance abaixo"
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            onClick={(state) => {
              const point = data[Number(state?.activeTooltipIndex)];
              if (state?.activeTooltipIndex != null && point && onSelect)
                onSelect(point.lance);
            }}
            margin={{ top: 8, right: 12, bottom: 0, left: -28 }}
          >
            <defs>
              <linearGradient id="evaluation-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#65c8a8" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#65c8a8" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="lance"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              minTickGap={25}
            />
            <YAxis
              domain={[-10, 10]}
              ticks={[-10, 0, 10]}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <div className="chart-tooltip">
                    Meio-lance {payload[0].payload.lance} ·{" "}
                    {evaluation(payload[0].payload)}
                  </div>
                ) : null
              }
            />
            <Area
              type="linear"
              dataKey="value"
              stroke="#65c8a8"
              fill="url(#evaluation-fill)"
              strokeWidth={2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {onSelect && (
        <details className="chart-access">
          <summary>Navegar pelos pontos do gráfico</summary>
          <div className="chart-points">
            {points.map((p) => (
              <button key={p.lance} onClick={() => onSelect(p.lance)}>
                Lance {p.lance}: {evaluation(p)}
              </button>
            ))}
          </div>
        </details>
      )}
    </>
  );
}

function Explanation({ move, demo, disabled, onSave }) {
  const [explanation, setExplanation] = useState(move?.explicacao);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function explain() {
    if (!move || demo) return;
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setBusy(true);
    setError("");
    try {
      const result = await api.explicar(
        { fen: move.fen_antes, lance_jogado: move.san },
        c.signal,
      );
      if (!c.signal.aborted) {
        setExplanation(result);
        onSave(result);
      }
    } catch (e) {
      if (!c.signal.aborted) setError(e.message);
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <section
      className="panel explanation-panel"
      aria-labelledby="explanation-title"
    >
      <div className="section-heading">
        <h2 id="explanation-title">
          <Sparkles size={19} />
          Entenda o lance
        </h2>
        {move && <ClassBadge value={move.classe} />}
      </div>
      {!move ? (
        <Empty icon={BookOpen} title="Uma posição, uma lição">
          Selecione um lance para explorar a explicação do treinador.
        </Empty>
      ) : (
        <>
          <div className="move-comparison">
            <div>
              <span>Você jogou</span>
              <b>{move.san}</b>
            </div>
            <div className="best-move">
              <span>Melhor alternativa</span>
              <b>{explanation?.melhor_lance || move.melhor_lance || "—"}</b>
            </div>
            <div>
              <span>Perda de chance</span>
              <b>
                {Number(move.queda || 0).toFixed(1)} <small>p.p.</small>
              </b>
            </div>
          </div>
          {busy ? (
            <Loading>O treinador está preparando a explicação…</Loading>
          ) : explanation?.validada ? (
            <div className="explanation-content">
              <span className="theme-tag">
                <Target size={14} />
                {explanation.tema_label || "Conceito da posição"}
              </span>
              <p>{explanation.texto}</p>
              {explanation.ficha && (
                <div className="concept-source">
                  <BookOpen size={16} />
                  <span>
                    Conceito consultado:{" "}
                    <strong>{explanation.ficha.titulo}</strong>
                  </span>
                </div>
              )}
              {explanation.fallback && (
                <p className="field-hint">
                  Explicação de apoio baseada nos dados do motor.
                </p>
              )}
              <ToolList tools={explanation.ferramentas_usadas} />
            </div>
          ) : (
            <div className="explanation-placeholder">
              <p>
                {explanation
                  ? "Não foi possível validar uma explicação para esta posição."
                  : demo
                    ? "Explore o lance 2. g4 para ver a explicação preparada nesta demonstração."
                    : "Descubra o que mudou nesta posição e como escolher uma alternativa melhor."}
              </p>
              {!demo && (
                <button
                  className="button primary"
                  onClick={explain}
                  disabled={disabled}
                >
                  <Sparkles size={16} />
                  {explanation
                    ? "Tentar explicar novamente"
                    : "Explicar este lance"}
                </button>
              )}
            </div>
          )}
          {error && <ErrorNotice onRetry={explain}>{error}</ErrorNotice>}
          {move.linha_motor?.length > 0 && (
            <details className="engine-line">
              <summary>Ver variante do motor</summary>
              <p>{move.linha_motor.join(" · ")}</p>
            </details>
          )}
        </>
      )}
    </section>
  );
}

function Chat({ fen, demo, disabled }) {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function send(event) {
    event.preventDefault();
    if (!question.trim() || busy || disabled) return;
    const text = question.trim();
    setBusy(true);
    setError("");
    const c = new AbortController();
    controller.current = c;
    try {
      const result = demo
        ? {
            resposta:
              "Este é um chat de demonstração, sem IA conectada. No lance 2. g4, as brancas abrem a diagonal até o rei e permitem Qh4#. Na aplicação conectada, suas perguntas são enviadas com a posição atual ao treinador.",
            validada: true,
            status: "ok",
            ferramentas_usadas: [],
          }
        : await api.chat(
            {
              fen,
              pergunta: text,
              historico: messages
                .filter((m) => m.validada !== false)
                .slice(-12)
                .map(({ role, content }) => ({
                  role,
                  content: content.slice(0, 2000),
                })),
            },
            c.signal,
          );
      if (!c.signal.aborted) {
        setMessages((items) => [
          ...items,
          { role: "user", content: text },
          {
            role: "assistant",
            content: result.validada
              ? result.resposta
              : "O treinador está indisponível para esta posição. Tente novamente em instantes.",
            validada: result.validada,
            tools: result.ferramentas_usadas,
          },
        ]);
        setQuestion("");
      }
    } catch (e) {
      if (!c.signal.aborted) setError(e.message);
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="panel chat-panel" aria-labelledby="chat-title">
      <div className="section-heading">
        <h2 id="chat-title">
          <MessageCircle size={19} />
          Converse com o treinador
        </h2>
        <span className="field-hint">Posição atual</span>
      </div>
      <div className="chat-messages" aria-live="polite" role="log">
        {!messages.length && (
          <p className="chat-intro">
            Ficou alguma dúvida? Pergunte sobre o tabuleiro. Ao mudar de
            posição, você começa uma nova conversa.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-message ${m.role}`}>
            <strong>{m.role === "user" ? "Você" : "Treinador"}</strong>
            <p>{m.content}</p>
            {m.tools && <ToolList tools={m.tools} />}
          </div>
        ))}
        {busy && <Loading>Consultando a posição…</Loading>}
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <form className="chat-form" onSubmit={send}>
        <label htmlFor="question" className="sr-only">
          Pergunta sobre a posição atual
        </label>
        <input
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={2000}
          placeholder="O que eu deveria observar nesta posição?"
          required
          disabled={disabled || busy}
        />
        <IconButton
          label="Enviar pergunta"
          disabled={disabled || busy || !question.trim()}
          type="submit"
        >
          <Send size={18} />
        </IconButton>
      </form>
    </section>
  );
}

function Report({ user, demo, onUser }) {
  const [name, setName] = useState(user || "");
  const [data, setData] = useState(demo ? demoReport : null);
  const [busy, setBusy] = useState(!demo && !!user);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const [retry, setRetry] = useState(0);
  const [puzzle, setPuzzle] = useState(null);
  useEffect(() => {
    if (demo || !user) return;
    const c = new AbortController();
    setBusy(true);
    setError("");
    setOffline(false);
    api
      .relatorio(user, c.signal)
      .then((result) => {
        if (!c.signal.aborted) {
          setData(result);
          writeCache(`report:${user}`, result);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setError(e.message);
          const cached = readCache(`report:${user}`);
          if (cached) {
            setData(cached);
            setOffline(true);
          }
        }
      })
      .finally(() => {
        if (!c.signal.aborted) setBusy(false);
      });
    return () => c.abort();
  }, [user, demo, retry]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">MEU PROGRESSO</span>
          <h1>
            Cada partida conta<span className="accent">.</span>
          </h1>
          <p>Seus pontos de atenção e o treino que faz sentido para você.</p>
        </div>
      </div>
      {!demo && (
        <form
          className="report-search"
          onSubmit={(e) => {
            e.preventDefault();
            onUser(name.trim());
            setRetry((n) => n + 1);
          }}
        >
          <label htmlFor="report-user">Jogador</label>
          <input
            id="report-user"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={100}
            placeholder="Identificador usado na importação"
          />
          <button className="button secondary" disabled={busy}>
            <Activity size={17} />
            Atualizar relatório
          </button>
        </form>
      )}
      {error && (
        <ErrorNotice onRetry={() => setRetry((n) => n + 1)}>
          {error}
        </ErrorNotice>
      )}
      {offline && (
        <div className="notice">
          Relatório salvo neste navegador. Reconecte o servidor para atualizar
          os resultados.
        </div>
      )}
      {busy ? (
        <Loading>Reunindo seus resultados e recomendações…</Loading>
      ) : !data || !data.partidas_analisadas ? (
        <div className="panel">
          <Empty
            icon={ChartNoAxesCombined}
            title="Seu progresso começa na primeira análise"
          >
            Importe e analise uma partida com este identificador para descobrir
            seus padrões.
            <p>
              <a className="button primary" href="#/">
                Importar partida
              </a>
            </p>
          </Empty>
        </div>
      ) : (
        <>
          <section className="report-stats">
            <Stat
              icon={Swords}
              label="Partidas analisadas"
              value={data.partidas_analisadas}
            />
            <Stat
              icon={Trophy}
              label="Rating médio das partidas"
              value={data.rating_estimado ?? "—"}
            />
            <Stat
              icon={Target}
              label="Temas para desenvolver"
              value={data.temas_fracos.length}
            />
            <Stat
              icon={BookOpen}
              label="Puzzles para praticar"
              value={data.puzzles_recomendados.length}
            />
          </section>
          <div className="report-grid">
            <section className="panel weakness-panel">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">ONDE FOCAR</span>
                  <h2>Seus pontos de atenção</h2>
                </div>
                <Target size={21} />
              </div>
              {!data.temas_fracos.length ? (
                <Empty icon={Check} title="Ainda sem temas classificados">
                  Abra os erros das suas partidas e peça as explicações para
                  identificar os conceitos envolvidos.
                </Empty>
              ) : (
                <div className="theme-bars">
                  {data.temas_fracos.map((theme, i) => (
                    <div key={theme.tema}>
                      <div>
                        <b>{theme.tema_label}</b>
                        <span>
                          {theme.erros} {theme.erros === 1 ? "erro" : "erros"}
                        </span>
                      </div>
                      <div className="bar-track">
                        <span
                          style={{
                            width: `${(theme.erros / Math.max(...data.temas_fracos.map((t) => t.erros), 1)) * 100}%`,
                            backgroundColor: [
                              "#78cfaf",
                              "#78aeca",
                              "#b5a2d2",
                              "#dab46d",
                            ][i % 4],
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {data.erros_sem_tema > 0 && (
                <p className="field-hint">
                  {data.erros_sem_tema} erros ainda sem tema identificado. Gere
                  explicações para enriquecer este relatório.
                </p>
              )}
            </section>
            <section className="panel evolution-panel">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">UMA PARTIDA DE CADA VEZ</span>
                  <h2>Sua evolução</h2>
                </div>
                <Activity size={21} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Data</th>
                      <th>Precisão</th>
                      <th>Erros graves</th>
                      <th>
                        <span className="sr-only">Abrir</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.evolucao.map((item) => (
                      <tr key={item.partida_id}>
                        <td>{dateLabel(item.data)}</td>
                        <td>
                          {item.precisao == null
                            ? "—"
                            : `${item.precisao.toFixed(1)}%`}
                        </td>
                        <td>{item.erros_graves}</td>
                        <td>
                          <a
                            href={
                              demo
                                ? "#/demo/analise/demo"
                                : `#/analise/${item.partida_id}`
                            }
                            aria-label={`Abrir partida de ${dateLabel(item.data)}`}
                          >
                            <ChevronRight size={18} />
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
          <section className="puzzles-section">
            <div className="section-heading">
              <div>
                <span className="eyebrow">COLOQUE EM PRÁTICA</span>
                <h2>Seu próximo treino</h2>
                <p>
                  {demo
                    ? "Exercício ilustrativo da demonstração."
                    : data.puzzles_personalizados_por_tema
                      ? "Puzzles selecionados pelos seus temas de atenção e faixa de rating."
                      : "Recomendações gerais por faixa de rating. Mais explicações permitem personalizar seus temas."}
                </p>
              </div>
              <span className="badge">
                <Flag size={14} />
                Treino tático
              </span>
            </div>
            {data.aviso_puzzles && (
              <div className="notice">{data.aviso_puzzles}</div>
            )}
            {!data.puzzles_recomendados.length ? (
              <div className="panel">
                <Empty icon={Target} title="Nenhum puzzle disponível agora">
                  Seus resultados continuam salvos. Atualize o relatório mais
                  tarde.
                </Empty>
              </div>
            ) : (
              <div className="puzzle-grid">
                {data.puzzles_recomendados.map((p, i) => (
                  <article className="panel puzzle-card" key={p.id}>
                    <div className="puzzle-preview">
                      <Chessboard
                        options={{
                          id: `puzzle-${p.id}`,
                          position: p.fen,
                          boardOrientation:
                            p.fen.split(" ")[1] === "b" ? "black" : "white",
                          allowDragging: false,
                          allowDrawingArrows: false,
                          showNotation: false,
                          darkSquareStyle: { backgroundColor: "#52766a" },
                          lightSquareStyle: { backgroundColor: "#e0e7df" },
                        }}
                      />
                    </div>
                    <div className="puzzle-body">
                      <span className="eyebrow">
                        EXERCÍCIO {String(i + 1).padStart(2, "0")}
                      </span>
                      <h3>
                        {p.temas_label?.slice(0, 2).join(" · ") ||
                          "Treino de tática"}
                      </h3>
                      <p>
                        Rating {p.rating} ·{" "}
                        {p.fen.split(" ")[1] === "b" ? "Pretas" : "Brancas"}{" "}
                        jogam
                      </p>
                      <button
                        className="button secondary full-width"
                        onClick={() => setPuzzle(p)}
                      >
                        <Target size={16} />
                        Explorar puzzle
                      </button>
                      {safeTrainingUrl(p.url) && (
                        <a
                          className="external-link"
                          href={safeTrainingUrl(p.url)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Treinar na Lichess <ExternalLink size={13} />
                        </a>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
      {puzzle && (
        <PuzzleDialog puzzle={puzzle} onClose={() => setPuzzle(null)} />
      )}
    </>
  );
}
function Stat({ icon: Icon, label, value }) {
  return (
    <div className="panel report-stat">
      <span className="stat-icon">
        <Icon size={22} />
      </span>
      <div>
        <span>{label}</span>
        <b>{value}</b>
      </div>
    </div>
  );
}

function PuzzleDialog({ puzzle, onClose }) {
  const dialog = useRef(null);
  const [show, setShow] = useState(false);
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current.showModal();
    return () => previous?.focus();
  }, []);
  return (
    <dialog
      className="puzzle-dialog"
      ref={dialog}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === dialog.current) onClose();
      }}
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">PAUSA PARA TREINAR</span>
          <h2>Encontre o melhor lance</h2>
        </div>
        <IconButton label="Fechar puzzle" onClick={onClose}>
          <X size={20} />
        </IconButton>
      </div>
      <Chessboard
        options={{
          id: "puzzle-dialog",
          position: puzzle.fen,
          boardOrientation:
            puzzle.fen.split(" ")[1] === "b" ? "black" : "white",
          allowDragging: false,
          allowDrawingArrows: false,
          arrows: show
            ? [arrow(puzzle.solucao[0], "#42ba9acc")].filter(Boolean)
            : [],
          darkSquareStyle: { backgroundColor: "#52766a" },
          lightSquareStyle: { backgroundColor: "#e0e7df" },
        }}
      />
      <p>
        {puzzle.fen.split(" ")[1] === "b" ? "Pretas" : "Brancas"} jogam · Rating{" "}
        {puzzle.rating}
      </p>
      <button
        className="button primary full-width"
        onClick={() => setShow(!show)}
      >
        {show ? "Ocultar primeira jogada" : "Revelar primeira jogada"}
      </button>
      {safeTrainingUrl(puzzle.url) && (
        <a
          className="external-link"
          href={safeTrainingUrl(puzzle.url)}
          target="_blank"
          rel="noreferrer"
        >
          Resolver sequência completa na Lichess <ExternalLink size={14} />
        </a>
      )}
    </dialog>
  );
}
