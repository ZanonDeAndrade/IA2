"""Classificação dos lances pela queda na chance de vitória.

A avaliação do motor em centipeões (``cp``, do ponto de vista do jogador) é
convertida em chance de vitória de 0 a 100 % pela mesma curva logística usada
pela Lichess::

    vitoria(cp) = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)

A queda ``delta = vitoria(cp_antes) - vitoria(cp_depois)`` define a classe:

    delta >= 30        -> erro_grave
    20 <= delta < 30   -> erro
    10 <= delta < 20   -> imprecisao
    delta < 10         -> aceitavel

Mate forçado é tratado como 100 % (a favor) ou 0 % (contra). Os limites ficam
em ``LIMITES`` e devem ter testes unitários.
"""

COEFICIENTE_LOGISTICO = 0.00368208

LIMITES = {
    "erro_grave": 30.0,
    "erro": 20.0,
    "imprecisao": 10.0,
}

CLASSES = ("aceitavel", "imprecisao", "erro", "erro_grave")


def chance_de_vitoria(cp: int | None, mate: int | None = None) -> float:
    """Converte uma avaliação do motor em chance de vitória (0 a 100).

    Args:
        cp: avaliação em centipeões do ponto de vista do jogador, ou ``None``
            quando há mate forçado.
        mate: lances até o mate (positivo a favor do jogador, negativo contra);
            ``None`` quando não há mate.

    Returns:
        Chance de vitória em pontos percentuais.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def classificar_lance(cp_antes: int, cp_depois: int) -> str:
    """Classifica um lance pela queda na chance de vitória.

    Args:
        cp_antes: avaliação (centipeões, ponto de vista do jogador) antes do lance.
        cp_depois: avaliação após o lance, no mesmo ponto de vista.

    Returns:
        Uma das classes em ``CLASSES``: ``"aceitavel"``, ``"imprecisao"``,
        ``"erro"`` ou ``"erro_grave"``.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
