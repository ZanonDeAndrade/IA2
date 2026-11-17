import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceLink } from "./SourceLink";

describe("SourceLink", () => {
  it("abre fontes http(s) em nova aba com noopener noreferrer", () => {
    render(<SourceLink title="Omelete" url="https://example.org/omelete" />);
    const link = screen.getByRole("link", { name: /Omelete/ });
    expect(link).toHaveAttribute("href", "https://example.org/omelete");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it.each(["javascript:alert(1)", "data/raw/livro.pdf#page=9", "file:///etc/passwd"])(
    "não cria link para %s",
    (url) => {
      render(<SourceLink title="Fonte" url={url} />);
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.getByText(`(${url})`)).toBeInTheDocument();
    },
  );
});
