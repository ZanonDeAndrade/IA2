import type { ConsultationOutput, RecipeCard as RecipeCardData } from "../types/api";
import { RecipeCard } from "./RecipeCard";
import { SourceLink } from "./SourceLink";

interface ResultListProps {
  result: ConsultationOutput;
}

interface Group {
  id: string;
  title: string;
  hint: string;
  recipes: RecipeCardData[];
}

/** Separa o que dá para preparar agora do que exige compra; a compatibilidade vem do backend (programática). */
export function groupRecipes(recipes: RecipeCardData[]): Group[] {
  const complete = recipes.filter((r) => r.compatibility === "COMPLETE");
  const partial = recipes.filter((r) => r.compatibility === "PARTIAL");
  const other = recipes.filter((r) => r.compatibility !== "COMPLETE" && r.compatibility !== "PARTIAL");
  const evaluated = complete.length > 0 || partial.length > 0;
  return [
    {
      id: "complete",
      title: "Você pode preparar agora",
      hint: "Você informou todos os ingredientes obrigatórios. Confira as quantidades na receita.",
      recipes: complete,
    },
    {
      id: "partial",
      title: "Com ingredientes adicionais",
      hint: "Estas receitas usam parte dos seus ingredientes; os que faltam estão indicados em cada uma.",
      recipes: partial,
    },
    {
      id: "other",
      title: evaluated ? "Outras receitas encontradas" : "Receitas encontradas",
      hint: evaluated ? "Não usam os ingredientes informados." : "",
      recipes: other,
    },
  ].filter((g) => g.recipes.length > 0);
}

/** Resposta FOUND: texto da resposta (sempre como texto, nunca HTML), cards agrupados e fontes da consulta. */
export function ResultList({ result }: ResultListProps) {
  const groups = groupRecipes(result.recipes);
  const hasComplete = result.recipes.some((r) => r.compatibility === "COMPLETE");
  const hasPartial = result.recipes.some((r) => r.compatibility === "PARTIAL");

  return (
    <section className="results" aria-labelledby="results-title">
      <h2 id="results-title">Resposta fundamentada no nosso catálogo</h2>
      <p className="results__answer">{result.answer}</p>

      {hasPartial && !hasComplete ? (
        <p className="results__notice" role="note">
          Nenhuma receita totalmente compatível com os seus ingredientes foi encontrada na base. As alternativas abaixo
          exigem ingredientes adicionais.
        </p>
      ) : null}

      {groups.map((group) => (
        <section key={group.id} className={`results__group results__group--${group.id}`} aria-labelledby={`group-${group.id}`}>
          <header className="results__group-header">
            <h3 id={`group-${group.id}`}>
              {group.title} <span className="results__count">({group.recipes.length})</span>
            </h3>
            {group.hint ? <p className="field__hint">{group.hint}</p> : null}
          </header>
          <ul className="results__cards">
            {group.recipes.map((recipe) => (
              <li key={recipe.recipe_id}>
                <RecipeCard recipe={recipe} />
              </li>
            ))}
          </ul>
        </section>
      ))}

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
