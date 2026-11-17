import type { ConsultationOutput } from "../types/api";
import { RecipeCard } from "./RecipeCard";
import { SourceLink } from "./SourceLink";

interface ResultListProps {
  result: ConsultationOutput;
}

/** Resposta FOUND: texto da resposta (sempre como texto, nunca HTML), cards e fontes da consulta. */
export function ResultList({ result }: ResultListProps) {
  return (
    <section className="results" aria-labelledby="results-title">
      <h2 id="results-title">Resposta fundamentada no nosso catálogo</h2>
      <p className="results__answer">{result.answer}</p>

      {result.recipes.length ? (
        <ul className="results__cards">
          {result.recipes.map((recipe) => (
            <li key={recipe.recipe_id}>
              <RecipeCard recipe={recipe} />
            </li>
          ))}
        </ul>
      ) : null}

      {result.sources.length ? (
        <section className="results__sources" aria-labelledby="sources-title">
          <h3 id="sources-title">Fontes consultadas</h3>
          <ul>
            {result.sources.map((src) => (
              <li key={`${src.document_id}-${src.recipe_id}`}>
                <SourceLink title={src.title} url={src.url} />
                {src.license ? <span className="results__license"> · Licença: {src.license}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="results__meta">Identificador da consulta: {result.request_id}</p>
    </section>
  );
}
