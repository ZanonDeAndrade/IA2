"""Ferramenta de importação de partidas da API pública do Chess.com.

A API não exige chave, mas exige um cabeçalho ``User-Agent`` identificando o
app e um contato (``CHESSCOM_USER_AGENT``); sem ele a resposta é 403. As
requisições devem ser feitas em série e os meses já baixados ficam em cache.

Endpoints usados:
    GET https://api.chess.com/pub/player/{usuario}/games/archives
    GET https://api.chess.com/pub/player/{usuario}/games/{AAAA}/{MM}
"""


def buscar_partidas(usuario: str, max: int = 10, ritmo: str | None = None) -> list[dict]:
    """Busca as últimas partidas concluídas de um usuário do Chess.com.

    Percorre os arquivos mensais do mais recente para o mais antigo até reunir
    ``max`` partidas.

    Args:
        usuario: nome de usuário no Chess.com (perfil público).
        max: quantidade máxima de partidas (padrão 10).
        ritmo: filtro opcional de ritmo (``"bullet"``, ``"blitz"``, ``"rapid"``,
            ``"daily"``); ``None`` traz todos.

    Returns:
        Lista de partidas, cada uma com PGN, cores, resultado, abertura, ritmo,
        data e URL da partida.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
