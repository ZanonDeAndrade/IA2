import type { ReactNode } from "react";

export type NoticeTone = "info" | "warning" | "error";

interface StatusNoticeProps {
  tone: NoticeTone;
  title: string;
  children?: ReactNode;
  action?: { label: string; onClick: () => void };
}

/** Aviso textual de estado (carregando, sem evidência, bloqueado, erro). Não depende só de cor. */
export function StatusNotice({ tone, title, children, action }: StatusNoticeProps) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "error" ? "alert" : "status"}>
      <p className="notice__title">{title}</p>
      {children ? <div className="notice__body">{children}</div> : null}
      {action ? (
        <button type="button" className="button button--secondary" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
