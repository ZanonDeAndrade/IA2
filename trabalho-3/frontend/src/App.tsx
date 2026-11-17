import { useRef } from "react";
import { ConsultationForm } from "./components/ConsultationForm";
import { ResultList } from "./components/ResultList";
import { StatusNotice } from "./components/StatusNotice";
import { useConsultation, type ConsultationState } from "./hooks/useConsultation";

function Status({ state, onEdit, onRetry }: { state: ConsultationState; onEdit: () => void; onRetry: () => void }) {
  const edit = { label: "Editar consulta", onClick: onEdit };
  switch (state.phase) {
    case "idle":
      return null;
    case "validating":
      return (
        <StatusNotice tone="error" title="Revise a consulta">
          <ul>
            {state.validationErrors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </StatusNotice>
      );
    case "loading":
      return (
        <StatusNotice tone="info" title={state.retrying ? "Reenviando a consulta…" : "Consultando a base de receitas…"}>
          <p>O modelo roda localmente e consulta a base de receitas; a resposta pode levar alguns minutos.</p>
        </StatusNotice>
      );
    case "success":
      return state.result ? <ResultList result={state.result} /> : null;
    case "empty":
      return (
        <StatusNotice tone="info" title="Não encontrei evidência suficiente na base" action={edit}>
          <p>{state.result?.answer}</p>
        </StatusNotice>
      );
    case "blocked":
      return (
        <StatusNotice tone="warning" title="Não posso responder a essa consulta" action={edit}>
          <p>{state.result?.answer}</p>
        </StatusNotice>
      );
    case "error":
      return (
        <StatusNotice tone="error" title="Não foi possível concluir a consulta" action={{ label: "Tentar novamente", onClick: onRetry }}>
          <p>{state.result?.error?.message ?? state.failure}</p>
          {state.result ? <p className="notice__meta">Identificador da consulta: {state.result.request_id}</p> : null}
        </StatusNotice>
      );
  }
}

export default function App() {
  const { state, submit, retry } = useConsultation();
  const questionRef = useRef<HTMLTextAreaElement>(null);

  return (
    <div className="app">
      <header className="app__header">
        <p className="app__brand">Chef IA</p>
        <h1>Assistente Inteligente de Receitas</h1>
        <p className="app__tagline">O que você tem na cozinha?</p>
      </header>
      <main className="app__main">
        <ConsultationForm onSubmit={submit} loading={state.phase === "loading"} questionRef={questionRef} />
        <div className="app__status" aria-live="polite">
          <Status state={state} onEdit={() => questionRef.current?.focus()} onRetry={retry} />
        </div>
      </main>
    </div>
  );
}
