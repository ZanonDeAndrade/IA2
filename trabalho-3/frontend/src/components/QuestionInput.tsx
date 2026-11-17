import type { Ref } from "react";
import { LIMITS } from "../types/api";

interface QuestionInputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ref?: Ref<HTMLTextAreaElement> | undefined;
}

export function QuestionInput({ id, value, onChange, disabled = false, ref }: QuestionInputProps) {
  const counterId = `${id}-counter`;
  return (
    <div className="field">
      <label htmlFor={id}>Pergunta (opcional)</label>
      <textarea
        id={id}
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={3}
        maxLength={LIMITS.questionMax}
        placeholder="Ex.: O que posso preparar para o café da manhã?"
        aria-describedby={counterId}
      />
      <p id={counterId} className="field__hint">
        {value.length}/{LIMITS.questionMax} caracteres
      </p>
    </div>
  );
}
