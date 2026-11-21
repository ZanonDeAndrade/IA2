"""Gera e verifica a amostra a partir de fontes rastreáveis."""

import argparse
from collections import Counter
import csv
from hashlib import file_digest, sha256
import io
from itertools import islice
import json
import os
from pathlib import Path
from shutil import which

import chess
import chess.engine
import chess.pgn
from dotenv import load_dotenv

from agent.classifier import chance_de_vitoria
from agent.validator import ler_fen

PASTA = Path(__file__).resolve().parent
FONTE_LICHESS = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
SEMENTE = 20261119
PROFUNDIDADE = 16
MIN_QUEDA = 20.0
ESTRATOS = {
    "fork": ("garfo", 9), "pin": ("cravada", 9), "skewer": ("espeto", 9),
    "discoveredAttack": ("ataque_descoberto", 9), "hangingPiece": ("peca_pendurada", 9),
    "mate": ("mate", 9), "deflection": ("desvio", 8), "attraction": ("atracao", 8),
}
TEMAS = {tema for tema, _ in ESTRATOS.values()}
COLUNAS = ("PuzzleId", "FEN", "Moves", "Rating", "Themes", "GameUrl")


def linhas_jsonl(caminho: Path) -> list[dict]:
    with caminho.open(encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def escrever_jsonl(caminho: Path, linhas) -> None:
    caminho.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in linhas), encoding="utf-8")


def hash_arquivo(caminho: Path) -> str:
    with caminho.open("rb") as arquivo:
        return file_digest(arquivo, "sha256").hexdigest()


def posicao_chave(tabuleiro: chess.Board) -> str:
    return " ".join(tabuleiro.fen().split()[:4])


def lance_legal(tabuleiro: chess.Board, notacao: str) -> chess.Move:
    lance = tabuleiro.parse_san(notacao)
    if lance not in tabuleiro.legal_moves:
        raise ValueError(f"Lance ilegal: {notacao}")
    if notacao.endswith(("+", "#")) and notacao[-1] != tabuleiro.san(lance)[-1]:
        raise ValueError(f"Indicação de xeque incorreta: {notacao}")
    return lance


def validar_exemplo(item: dict) -> tuple[str, str]:
    tabuleiro = ler_fen(item["fen"])
    jogado = lance_legal(tabuleiro, item["lance_jogado"])
    melhor = lance_legal(tabuleiro, item["melhor_lance"])
    if jogado == melhor or item["tema_esperado"] not in TEMAS:
        raise ValueError("O lance de referência deve diferir do erro, com tema conhecido.")
    origem = item["origem"]
    if origem["tipo"] not in {"lichess", "partida"} or not origem["id"] or not origem["url"]:
        raise ValueError("Origem incompleta.")
    if type(origem["rating"]) is not int or not 800 <= origem["rating"] <= 2000:
        raise ValueError("Rating fora do recorte.")
    if origem["tipo"] == "lichess":
        tags = origem["temas_lichess"]
        if not any(tag in tags and tema == item["tema_esperado"] for tag, (tema, _) in ESTRATOS.items()):
            raise ValueError("O rótulo esperado precisa constar na linha de origem.")
        linha_puzzle = origem["moves_uci"]
        if (len(linha_puzzle) < 2 or jogado.uci() != linha_puzzle[0]
                or linha_puzzle[1] != origem["resposta_do_puzzle_uci"]):
            raise ValueError("A trilha UCI não confirma a jogada anterior ou o início da solução.")
        depois = tabuleiro.copy(stack=False)
        for uci in linha_puzzle:
            lance = depois.parse_uci(uci)
            if not lance:
                raise ValueError("Lance nulo na fonte.")
            depois.push(lance)
    elif not all(isinstance(origem.get(campo), str) and origem[campo].strip()
                 for campo in ("rotulo_por", "pgn_sha256")) or any(
        type(origem.get(campo)) is not int or origem[campo] < 1 for campo in ("meio_lance", "partida_no_pgn")
    ):
        raise ValueError("Partida sem origem PGN ou rótulo rastreável.")
    motor = item["motor"]
    linha = motor["linha_principal"]
    if not linha or lance_legal(tabuleiro, linha[0]) != melhor:
        raise ValueError("A variante de referência precisa começar pelo melhor lance.")
    depois = tabuleiro.copy(stack=False)
    for san in linha:
        depois.push(lance_legal(depois, san))
    queda = _chance(motor["avaliacao"]) - _chance(motor["avaliacao_jogado"])
    if queda < MIN_QUEDA or abs(queda - motor["queda_pp"]) > 0.000001:
        raise ValueError("A referência do motor não confirma a perda mínima exigida.")
    return item["id"], posicao_chave(tabuleiro)


def carregar_dataset(caminho: str | Path = PASTA / "dataset.jsonl") -> list[dict]:
    dataset = linhas_jsonl(Path(caminho))
    ids, posicoes, fontes = set(), set(), set()
    for numero, item in enumerate(dataset, 1):
        try:
            id_, posicao = validar_exemplo(item)
            fonte = (item["origem"]["tipo"], item["origem"]["id"])
            if id_ in ids or posicao in posicoes or fonte in fontes:
                raise ValueError("Posição, fonte ou identificador duplicado.")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as erro:
            raise ValueError(f"Registro {numero} inválido em {caminho}: {erro}") from erro
        ids.add(id_)
        posicoes.add(posicao)
        fontes.add(fonte)
    return dataset


def _chance(avaliacao: dict) -> float:
    if avaliacao.get("tipo") == "mate":
        return 100.0 if avaliacao["a_favor"] else 0.0
    if avaliacao.get("tipo") == "cp":
        return chance_de_vitoria(avaliacao["valor"])
    raise ValueError("Tipo de avaliação desconhecido.")


def _pontuacao(info: dict, turno: bool) -> dict:
    score = info["score"].pov(turno)
    if score.is_mate():
        mate = score.mate()
        return {"tipo": "mate", "valor": mate, "a_favor": (mate or score.score(mate_score=1)) > 0}
    return {"tipo": "cp", "valor": score.score()}


def avaliar_jogada(motor, tabuleiro: chess.Board, jogado: chess.Move, profundidade: int) -> dict | None:
    """Compara a melhor opção com a jogada forçada no mesmo FEN e POV."""
    limite = chess.engine.Limit(depth=profundidade)
    info = motor.analyse(tabuleiro, limite, game=object())
    pv = info.get("pv", [])
    if not pv or pv[0] == jogado:
        return None
    forcado = motor.analyse(tabuleiro, limite, game=object(), root_moves=[jogado])
    melhor_score, jogado_score = (_pontuacao(i, tabuleiro.turn) for i in (info, forcado))
    queda = _chance(melhor_score) - _chance(jogado_score)
    if queda < MIN_QUEDA:
        return None
    copia = tabuleiro.copy(stack=False)
    linha = []
    for lance in pv[:8]:
        linha.append(copia.san(lance))
        copia.push(lance)
    return {"avaliacao": melhor_score, "avaliacao_jogado": jogado_score,
            "linha_principal": linha, "queda_pp": round(queda, 8)}


def _puzzle(row: dict) -> tuple[chess.Board, chess.Move, dict]:
    tabuleiro = ler_fen(row["FEN"])
    linha = row["Moves"].split()
    if len(linha) < 2:
        raise ValueError("Puzzle sem jogada anterior e resposta.")
    copia = tabuleiro.copy(stack=False)
    for uci in linha:
        lance = copia.parse_uci(uci)
        if not lance:
            raise ValueError("Lance nulo na fonte.")
        copia.push(lance)
    return tabuleiro, tabuleiro.parse_uci(linha[0]), {
        "tipo": "lichess", "id": row["PuzzleId"], "url": f"https://lichess.org/training/{row['PuzzleId']}",
        "partida_url": row["GameUrl"], "rating": int(row["Rating"]), "moves_uci": linha,
        "resposta_do_puzzle_uci": linha[1], "temas_lichess": row["Themes"].split(),
    }


def candidatos_lichess(caminho: Path, limite: int, semente: int) -> dict[str, list[dict]]:
    """Seleciona o prefixo da fonte e ranqueia por hash para cada tema."""
    def ler(arquivo):
        bolsas = {tag: [] for tag in ESTRATOS}
        for row in islice(csv.DictReader(arquivo), limite):
            if not all(row.get(k) for k in COLUNAS) or not str(row["Rating"]).isdigit():
                continue
            if not 800 <= int(row["Rating"]) <= 2000:
                continue
            reduzida = {k: row[k] for k in COLUNAS}
            for tag in set(row["Themes"].split()) & ESTRATOS.keys():
                bolsas[tag].append(reduzida)
        return {tag: sorted(rows, key=lambda r: sha256(
            f"{semente}:{tag}:{r['PuzzleId']}".encode()).digest()) for tag, rows in bolsas.items()}

    if caminho.suffix == ".zst":
        import zstandard

        with caminho.open("rb") as arquivo, zstandard.ZstdDecompressor().stream_reader(arquivo) as stream:
            return ler(io.TextIOWrapper(stream, encoding="utf-8", newline=""))
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        return ler(arquivo)


def _percorrer_partida(jogo, caminho: Path):
    if jogo.errors or jogo.headers.get("Variant", "Standard") != "Standard":
        raise ValueError(f"PGN inválido ou de outra variante em {caminho.name}.")
    tabuleiro = ler_fen(jogo.board().fen())
    lances = list(jogo.mainline_moves())
    if not lances or any(not lance for lance in lances):
        raise ValueError(f"Partida sem linha principal válida em {caminho.name}.")
    for ply, lance in enumerate(lances, 1):
        yield ply, tabuleiro, lance
        tabuleiro.push(lance)


def _rating_pgn(jogo, tabuleiro: chess.Board) -> int | None:
    cor = "White" if tabuleiro.turn else "Black"
    elo = jogo.headers.get(cor + "Elo", "").strip()
    return int(elo) if elo.isdecimal() else None


def sugerir_partidas(caminhos: list[Path], motor, profundidade: int, destino: Path, base: list[dict]):
    """Encontra erros reais e gera um manifesto para revisão humana."""
    posicoes = {posicao_chave(ler_fen(item["fen"])) for item in base}
    arquivos = set()
    for caminho in caminhos:
        digest = hash_arquivo(caminho)
        if digest in arquivos:
            continue
        arquivos.add(digest)
        with caminho.open(encoding="utf-8-sig") as arquivo:
            for indice, jogo in enumerate(iter(lambda: chess.pgn.read_game(arquivo), None), 1):
                referencias = (jogo.headers.get("Link", ""), jogo.headers.get("Site", ""))
                url = next((ref for ref in referencias if ref.startswith(("https://", "http://"))), None)
                for ply, tabuleiro, lance in _percorrer_partida(jogo, caminho):
                    chave = posicao_chave(tabuleiro)
                    rating = _rating_pgn(jogo, tabuleiro)
                    if chave in posicoes or (rating is not None and not 800 <= rating <= 2000):
                        continue
                    analise = avaliar_jogada(motor, tabuleiro.copy(stack=False), lance, profundidade)
                    if analise is None:
                        continue
                    posicoes.add(chave)
                    yield {
                        "pgn": os.path.relpath(caminho, destino), "partida": indice, "meio_lance": ply,
                        "id_partida": f"{digest}:{indice}", "url": url,
                        "pgn_sha256": digest, "rating": rating, "tema_esperado": None, "rotulo_por": None,
                        "fen": tabuleiro.fen(), "lance_jogado": tabuleiro.san(lance), "motor": analise,
                    }


def _partidas(manifesto: Path):
    """Lê PGNs explicitamente indicados pelo grupo, com rótulo humano."""
    for entrada in linhas_jsonl(manifesto):
        caminho = manifesto.parent / entrada["pgn"]
        indice = entrada["partida"]
        ply = entrada["meio_lance"]
        if type(indice) is not int or indice < 1 or type(ply) is not int or ply < 1:
            raise ValueError("Os índices de partida e meio-lance começam em 1.")
        if not all(isinstance(entrada.get(campo), str) and entrada[campo].strip()
                   for campo in ("id_partida", "url", "rotulo_por")):
            raise ValueError("Informe a referência da partida e quem rotulou a posição.")
        digest = hash_arquivo(caminho)
        if entrada.get("pgn_sha256", digest) != digest:
            raise ValueError(f"PGN alterado após a seleção dos candidatos: {caminho.name}.")
        with caminho.open(encoding="utf-8-sig") as arquivo:
            jogo = None
            for _ in range(indice):
                jogo = chess.pgn.read_game(arquivo)
                if jogo is None:
                    raise ValueError(f"Partida {indice} ausente em {caminho.name}")
        posicao = next(islice(_percorrer_partida(jogo, caminho), ply - 1, ply), None)
        if posicao is None:
            raise ValueError(f"Meio-lance {ply} ausente em {caminho.name}")
        _, tabuleiro, lance = posicao
        rating = _rating_pgn(jogo, tabuleiro)
        if rating is None:
            rating = entrada.get("rating")
        if entrada["tema_esperado"] not in TEMAS or type(rating) is not int or not 800 <= rating <= 2000:
            raise ValueError("O tema ou rating da posição rotulada está fora do recorte.")
        yield tabuleiro, lance, entrada["tema_esperado"], {
            "tipo": "partida", "id": f"{entrada['id_partida']}:{ply}", "url": entrada["url"],
            "meio_lance": ply, "rating": rating, "rotulo_por": entrada["rotulo_por"],
            "pgn_sha256": digest, "partida_no_pgn": indice,
        }


def gerar(candidatos, motor, profundidade: int, manifesto: Path | None = None, *, base=()):
    dataset, examinados = list(base), []
    posicoes = {posicao_chave(ler_fen(item["fen"])) for item in dataset}
    ids = {item["id"] for item in dataset}
    puzzles = {item["origem"]["id"] for item in dataset if item["origem"]["tipo"] == "lichess"}
    cache = {}

    def adicionar(tabuleiro, jogado, tema, origem):
        chave = posicao_chave(tabuleiro)
        id_ = f"{origem['tipo']}:{origem['id']}"
        if chave in posicoes or id_ in ids:
            return False
        analise_chave = (tabuleiro.fen(), jogado.uci())
        if analise_chave not in cache:
            cache[analise_chave] = avaliar_jogada(motor, tabuleiro.copy(stack=False), jogado, profundidade)
        resultado = cache[analise_chave]
        if resultado is None:
            return False
        item = {"id": id_, "fen": tabuleiro.fen(),
                "lance_jogado": tabuleiro.san(jogado), "melhor_lance": resultado["linha_principal"][0],
                "tema_esperado": tema, "origem": origem, "motor": resultado}
        validar_exemplo(item)
        dataset.append(item)
        posicoes.add(chave)
        ids.add(id_)
        return True

    for tag, (tema, cota) in ESTRATOS.items():
        aceitos = 0
        for row in candidatos.get(tag, []):
            if row["PuzzleId"] in puzzles:
                continue
            examinados.append({"estrato": tag, "row": row})
            try:
                tabuleiro, jogado, origem = _puzzle(row)
            except (ValueError, KeyError):
                continue
            if adicionar(tabuleiro, jogado, tema, origem):
                puzzles.add(row["PuzzleId"])
                aceitos += 1
                if aceitos == cota:
                    break
    aceitos = sum(item["origem"]["tipo"] == "partida" for item in dataset)
    if manifesto and aceitos < 30:
        for tabuleiro, jogado, tema, origem in _partidas(manifesto):
            aceitos += adicionar(tabuleiro, jogado, tema, origem)
            if aceitos == 30:
                break
    return dataset, examinados


def main() -> None:
    load_dotenv(PASTA.parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    fontes = parser.add_mutually_exclusive_group(required=True)
    fontes.add_argument("--lichess", type=Path)
    fontes.add_argument("--candidatos", type=Path)
    fontes.add_argument("--pgn", nargs="+", type=Path, help="Gera candidatos PGN para rotulagem.")
    fontes.add_argument("--base", type=Path, help="Preserva os registros de um dataset e acrescenta --partidas.")
    parser.add_argument("--partidas", type=Path)
    parser.add_argument("--stockfish", default=os.getenv("STOCKFISH_PATH") or "stockfish")
    parser.add_argument("--profundidade", type=int, default=PROFUNDIDADE)
    parser.add_argument("--semente", type=int, default=SEMENTE)
    parser.add_argument("--limite", type=int, default=16000)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--salvar-candidatos", type=Path)
    parser.add_argument("--snapshot-lichess", help="Identificação do snapshot, como data ou ETag.")
    args = parser.parse_args()
    if args.profundidade < 1 or args.limite < 1:
        parser.error("A profundidade e o limite devem ser positivos.")
    if (args.pgn or args.base) and not args.saida:
        parser.error("Informe --saida para o manifesto de candidatos ou o dataset combinado.")
    if (args.pgn and args.partidas) or (args.base and not args.partidas):
        parser.error("Use --pgn para selecionar candidatos ou --base com --partidas para acrescentar posições rotuladas.")
    args.saida = args.saida or PASTA / "dataset.jsonl"
    entradas = [args.base, args.partidas, args.lichess, args.candidatos]
    if args.pgn:
        entradas.extend([PASTA / "dataset.jsonl", *args.pgn])
    if any(args.saida.resolve() == fonte.resolve() for fonte in entradas if fonte is not None):
        parser.error("Informe um arquivo de saída diferente das entradas.")
    base = carregar_dataset(args.base) if args.base else []
    meta_base = {}
    if args.base:
        arquivo_meta = args.base.with_suffix(".meta.json")
        if not arquivo_meta.is_file():
            parser.error("Inclua os metadados do dataset base para comparar os perfis Stockfish.")
        meta_base = json.loads(arquivo_meta.read_text(encoding="utf-8"))
        if meta_base.get("dataset_sha256") != hash_arquivo(args.base):
            parser.error("O hash do dataset base diverge dos metadados.")
    if args.lichess:
        candidatos = candidatos_lichess(args.lichess, args.limite, args.semente)
    else:
        candidatos = {tag: [] for tag in ESTRATOS}
        if args.candidatos:
            for item in linhas_jsonl(args.candidatos):
                candidatos[item["estrato"]].append(item["row"])
    executavel = which(args.stockfish)
    if executavel is None:
        parser.error("Configure --stockfish ou STOCKFISH_PATH com um executável UCI.")
    with chess.engine.SimpleEngine.popen_uci(executavel, timeout=30) as motor:
        if "stockfish" not in motor.id.get("name", "").lower():
            parser.error("O executável precisa identificar-se como Stockfish.")
        perfil = {"stockfish": motor.id["name"], "profundidade": args.profundidade,
                  "threads": 1, "hash_mib": 16, "multipv": 1}
        if meta_base and any(meta_base.get(chave, 1 if chave == "multipv" else None) != valor
                             for chave, valor in perfil.items()):
            parser.error("Use a mesma versão do Stockfish e o mesmo perfil do dataset base.")
        motor.configure({"Threads": 1, "Hash": 16})
        if args.pgn:
            sugestoes = list(sugerir_partidas(args.pgn, motor, args.profundidade, args.saida.parent, carregar_dataset()))
            escrever_jsonl(args.saida, sugestoes)
            print(f"{len(sugestoes)} posições candidatas aguardando revisão e rótulo em {args.saida}.")
            return
        dados, examinados = gerar(candidatos, motor, args.profundidade, args.partidas, base=base)
    escrever_jsonl(args.saida, dados)
    carregar_dataset(args.saida)
    if args.salvar_candidatos:
        escrever_jsonl(args.salvar_candidatos, examinados)
    resumo = {
        "fonte_lichess": FONTE_LICHESS, "semente": args.semente,
        "prefixo_registros": args.limite if args.lichess else None,
        "fonte_sha256": hash_arquivo(args.lichess or args.candidatos or args.base),
        "snapshot_lichess": args.snapshot_lichess,
        "dataset_sha256": hash_arquivo(args.saida), **perfil,
        "executavel_sha256": hash_arquivo(Path(executavel)),
        "limite_busca_s": None, "timeout_inicializacao_s": 30, "queda_minima_pp": MIN_QUEDA,
        "por_origem": dict(Counter(d["origem"]["tipo"] for d in dados)),
        "por_tema": dict(Counter(d["tema_esperado"] for d in dados)), "candidatos_examinados": len(examinados),
    }
    if args.base:
        resumo["base"] = meta_base
        resumo["manifesto_partidas_sha256"] = hash_arquivo(args.partidas)
    if args.salvar_candidatos:
        resumo["candidatos_sha256"] = hash_arquivo(args.salvar_candidatos)
    args.saida.with_suffix(".meta.json").write_text(json.dumps(resumo, indent=2) + "\n", encoding="utf-8")
    print(f"{len(dados)}/100 posições confirmadas. {resumo['por_origem']}")


if __name__ == "__main__":
    main()
