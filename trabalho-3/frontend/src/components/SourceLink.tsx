interface SourceLinkProps {
  title: string;
  url: string;
}

function isHttpUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

/** Link para a fonte documental. Referências que não são http(s) aparecem como texto, nunca como link. */
export function SourceLink({ title, url }: SourceLinkProps) {
  if (isHttpUrl(url)) {
    return (
      <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">
        {title}
        <span className="visually-hidden"> (abre em nova aba)</span>
      </a>
    );
  }
  return (
    <span className="source-link source-link--local">
      {title} <span className="source-link__ref">({url})</span>
    </span>
  );
}
