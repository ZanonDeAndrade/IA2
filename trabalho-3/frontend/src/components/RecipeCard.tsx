import { useId, useState } from "react";
import type { Compatibility, RecipeCard as RecipeCardData } from "../types/api";
import { SourceLink } from "./SourceLink";

function compatibilityLabel(compatibility: Compatibility, missing: number): string {
  switch (compatibility) {
    case "COMPLETE":
      return "Tem todos os ingredientes";
    case "PARTIAL":
      return missing === 1 ? "Falta 1 ingrediente" : `Faltam ${missing} ingredientes`;
    case "NO_MATCH":
      return "Nenhum dos seus ingredientes";
    case "NOT_EVALUATED":
      return "Compatibilidade não avaliada";
  }
}

/** "a gosto", "à vontade", "q.b." ficam depois do nome ("Sal a gosto"). */
const TO_TASTE = /^(a gosto|à vontade|a vontade|q\.?b\.?|quanto baste)$/i;

function listOrNone(items: string[]): string {
  return items.length ? items.join(", ") : "nenhum";
}

interface RecipeCardProps {
  recipe: RecipeCardData;
}

/** Card montado só com dados recuperados pelo backend via MCP; campos ausentes não são preenchidos. */
export function RecipeCard({ recipe }: RecipeCardProps) {
  const [showSteps, setShowSteps] = useState(false);
  const stepsId = useId();
  const titleId = useId();
  const evaluated = recipe.compatibility !== "NOT_EVALUATED";
  const category = recipe.topic_label
    ? recipe.subcategory
      ? `${recipe.topic_label} › ${recipe.subcategory}`
      : recipe.topic_label
    : null;
  const details = [
    recipe.portions ? `Rendimento: ${recipe.portions}` : null,
    recipe.preparation_time ? `Tempo: ${recipe.preparation_time}` : null,
    recipe.temperature ? `Temperatura: ${recipe.temperature}` : null,
  ].filter((d): d is string => d !== null);

  return (
    <article className="recipe-card" aria-labelledby={titleId}>
      <header className="recipe-card__header">
        <div>
          {category ? <p className="recipe-card__category">{category}</p> : null}
          <h3 id={titleId}>{recipe.title}</h3>
        </div>
        <span className={`badge badge--${recipe.compatibility.toLowerCase()}`}>
          {compatibilityLabel(recipe.compatibility, recipe.missing_ingredients.length)}
        </span>
      </header>

      {evaluated ? (
        <dl className="recipe-card__match">
          <div>
            <dt>Tenho</dt>
            <dd>{listOrNone(recipe.available_ingredients)}</dd>
          </div>
          <div>
            <dt>Faltam</dt>
            <dd>{listOrNone(recipe.missing_ingredients)}</dd>
          </div>
        </dl>
      ) : null}

      {details.length ? (
        <ul className="recipe-card__details">
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      ) : null}

      {recipe.ingredients.length ? (
        <section>
          <h4>Ingredientes da receita</h4>
          <ul className="recipe-card__ingredients">
            {recipe.ingredients.map((ing, i) => (
              <li key={`${ing.name}-${i}`}>
                {ing.quantity_text && !TO_TASTE.test(ing.quantity_text) ? `${ing.quantity_text} ` : ""}
                {ing.name}
                {ing.quantity_text && TO_TASTE.test(ing.quantity_text) ? ` ${ing.quantity_text}` : ""}
                {ing.required ? "" : " (opcional)"}
                {ing.notes ? ` — ${ing.notes}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {recipe.instructions.length ? (
        <section>
          <button
            type="button"
            className="button button--secondary"
            aria-expanded={showSteps}
            aria-controls={stepsId}
            onClick={() => setShowSteps((v) => !v)}
          >
            {showSteps ? "Ocultar preparo" : "Ver preparo"}
          </button>
          <ol id={stepsId} className="recipe-card__steps" hidden={!showSteps}>
            {recipe.instructions.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </section>
      ) : (
        <p className="recipe-card__note">O modo de preparo não foi recuperado da fonte.</p>
      )}

      <p className="recipe-card__source">
        Fonte: <SourceLink title={recipe.title} url={recipe.source_url} />
      </p>
    </article>
  );
}
