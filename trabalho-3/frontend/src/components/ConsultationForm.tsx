import { useState, type FormEvent, type Ref } from "react";
import { IngredientInput, mergeIngredients, splitIngredients } from "./IngredientInput";
import { QuestionInput } from "./QuestionInput";

interface ConsultationFormProps {
  onSubmit: (question: string, ingredients: string[]) => void;
  loading: boolean;
  questionRef?: Ref<HTMLTextAreaElement> | undefined;
}

export function ConsultationForm({ onSubmit, loading, questionRef }: ConsultationFormProps) {
  const [question, setQuestion] = useState("");
  const [ingredients, setIngredients] = useState<string[]>([]);
  const [draft, setDraft] = useState("");

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (loading) return;
    const all = mergeIngredients(ingredients, splitIngredients(draft));
    if (draft) {
      setIngredients(all);
      setDraft("");
    }
    onSubmit(question, all);
  };

  return (
    <form className="consultation-form" onSubmit={handleSubmit} aria-busy={loading} noValidate>
      <IngredientInput
        id="ingredients"
        items={ingredients}
        draft={draft}
        onItemsChange={setIngredients}
        onDraftChange={setDraft}
        disabled={loading}
      />
      <QuestionInput id="question" value={question} onChange={setQuestion} disabled={loading} ref={questionRef} />
      <button type="submit" className="button button--primary" disabled={loading}>
        {loading ? "Buscando…" : "Buscar receitas"}
      </button>
    </form>
  );
}
