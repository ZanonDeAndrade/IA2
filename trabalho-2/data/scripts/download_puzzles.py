"""Baixa a base de puzzles da Lichess e salva um recorte em SQLite.

Placeholder. Fluxo previsto:
    1. Baixar ``https://database.lichess.org/lichess_db_puzzle.csv.zst``.
    2. Descompactar em streaming (``zstandard``) sem gravar o CSV inteiro.
    3. Filtrar por faixa de rating e sortear ``quantidade`` puzzles, equilibrando
       os temas principais.
    4. Salvar em ``data/puzzles.sqlite`` (tabela ``puzzles`` com as colunas da
       base) para consulta pela ferramenta ``buscar_puzzles``.

Uso (a partir de ``trabalho-2/``):
    python data/scripts/download_puzzles.py --rating-min 600 --rating-max 2200 --quantidade 50000

A base completa e o recorte NÃO vão para o Git (ver ``data/README.md``).
"""

URL_BASE_PUZZLES = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
CAMINHO_SQLITE_PADRAO = "data/puzzles.sqlite"


def baixar_base(destino: str) -> str:
    """Baixa o arquivo ``.zst`` da Lichess para ``destino`` e devolve o caminho.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def recortar(caminho_zst: str, rating_min: int, rating_max: int, quantidade: int):
    """Lê o CSV compactado em streaming e devolve o recorte filtrado.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def salvar_sqlite(recorte, caminho_sqlite: str = CAMINHO_SQLITE_PADRAO) -> None:
    """Grava o recorte na tabela ``puzzles`` do banco SQLite.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def main() -> None:
    """Lê os argumentos da linha de comando e executa o fluxo completo.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


if __name__ == "__main__":
    main()
