"""Cache em SQLite: partidas importadas, análises e explicações já geradas.

Evita reprocessar partidas (RF11) e guarda o progresso das tarefas de análise.
O caminho do banco deve vir de configuração (variável de ambiente), e o arquivo
``*.db`` / ``*.sqlite`` nunca entra no Git.
"""

import sqlite3


def conectar(caminho: str | None = None) -> sqlite3.Connection:
    """Abre uma conexão com o banco (cria o arquivo se não existir).

    Args:
        caminho: caminho do arquivo SQLite; ``None`` usa o padrão da configuração.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def inicializar_banco(conn: sqlite3.Connection) -> None:
    """Cria as tabelas (partidas, lances, explicacoes, tarefas) se não existirem.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def salvar_partida(conn: sqlite3.Connection, partida: dict) -> str:
    """Salva uma partida importada e devolve o seu id.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def obter_partida(conn: sqlite3.Connection, partida_id: str) -> dict | None:
    """Devolve a partida com a análise (se já existir) ou ``None``.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def salvar_analise(conn: sqlite3.Connection, partida_id: str, lances: list[dict]) -> None:
    """Salva a análise lance a lance de uma partida.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def salvar_explicacao(conn: sqlite3.Connection, fen: str, lance: str, explicacao: dict) -> None:
    """Guarda em cache a explicação gerada para um par (posição, lance).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def atualizar_tarefa(conn: sqlite3.Connection, tarefa_id: str, progresso: dict) -> None:
    """Atualiza o status e o progresso de uma tarefa de análise.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
