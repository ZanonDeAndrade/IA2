import type { ClipboardEvent, KeyboardEvent } from "react";
import { LIMITS } from "../types/api";

interface IngredientInputProps {
  id: string;
  items: string[];
  draft: string;
  onItemsChange: (items: string[]) => void;
  onDraftChange: (draft: string) => void;
  disabled?: boolean;
}

/** Divide texto separado por vírgula ou ponto e vírgula em ingredientes, sem vazios. */
export function splitIngredients(text: string): string[] {
  return text
    .split(/[,;\n]/)
    .map((s) => s.trim().replace(/\s+/g, " "))
    .filter(Boolean);
}

/** Acrescenta ingredientes ignorando repetidos (sem diferenciar maiúsculas). */
export function mergeIngredients(items: string[], extra: string[]): string[] {
  const seen = new Set(items.map((i) => i.toLocaleLowerCase("pt-BR")));
  const out = [...items];
  for (const item of extra) {
    const key = item.toLocaleLowerCase("pt-BR");
    if (!seen.has(key)) {
      seen.add(key);
      out.push(item);
    }
  }
  return out;
}

export function IngredientInput({ id, items, draft, onItemsChange, onDraftChange, disabled = false }: IngredientInputProps) {
  const hintId = `${id}-hint`;

  const commit = (text: string) => {
    const extra = splitIngredients(text);
    if (extra.length) onItemsChange(mergeIngredients(items, extra));
    onDraftChange("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      if (draft.trim()) {
        e.preventDefault();
        commit(draft);
      } else if (e.key === ",") {
        e.preventDefault();
      }
    } else if (e.key === "Backspace" && !draft && items.length) {
      onItemsChange(items.slice(0, -1));
    }
  };

  const onPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData("text");
    if (/[,;\n]/.test(text)) {
      e.preventDefault();
      commit(draft + text);
    }
  };

  return (
    <div className="field">
      <label htmlFor={id}>Ingredientes que você tem</label>
      {items.length ? (
        <ul className="chips" aria-label="Ingredientes informados">
          {items.map((item) => (
            <li key={item} className="chip">
              <span>{item}</span>
              <button
                type="button"
                className="chip__remove"
                onClick={() => onItemsChange(items.filter((i) => i !== item))}
                disabled={disabled}
                aria-label={`Remover ${item}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <input
        id={id}
        type="text"
        value={draft}
        onChange={(e) => onDraftChange(e.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        onBlur={() => draft.trim() && commit(draft)}
        disabled={disabled}
        maxLength={LIMITS.ingredientMaxChars * 4}
        placeholder="ovo, queijo, tomate"
        aria-describedby={hintId}
        autoComplete="off"
      />
      <p id={hintId} className="field__hint">
        Separe por vírgula ou pressione Enter. Opcional, até {LIMITS.ingredientsMax} ingredientes.
      </p>
    </div>
  );
}
