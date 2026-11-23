import { CircleAlert, LoaderCircle } from "lucide-react";
import { CLASSES } from "../lib/chess";

export function ErrorNotice({ children, onRetry }) {
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

export function Loading({ children = "Carregando…" }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} />
      {children}
    </div>
  );
}

export function ClassBadge({ value }) {
  const c = CLASSES[value];
  if (!c) return <span className="badge">Sem classificação</span>;
  return (
    <span className={`badge class-${value}`}>
      <b>{c.symbol}</b>
      {c.label}
    </span>
  );
}

export function Player({ player, color, showRating = true }) {
  return (
    <div className="player">
      <span className={`piece-avatar ${color}`}>
        {color === "white" ? "♔" : "♚"}
      </span>
      <b>{player?.nome || (color === "white" ? "Brancas" : "Pretas")}</b>
      {showRating && <span>{player?.rating || "Sem rating"}</span>}
      <span className="player-color">
        {color === "white" ? "Brancas" : "Pretas"}
      </span>
    </div>
  );
}
