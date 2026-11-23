import { useMemo, useState } from "react";
import { Chess } from "chess.js";
import { Chessboard, defaultPieces } from "react-chessboard";
import { Player } from "../components/ChessUi";
import { arrow, BOARD_COLORS } from "../lib/chess";

const PIECE_NAMES = {
  k: "rei", q: "dama", r: "torre", b: "bispo", n: "cavalo", p: "peão",
};

export default function GameBoard({ fen, color, playable, legalMoves, lastMove, tip, visuals, onMove, onIllegal }) {
  const board = useMemo(() => new Chess(fen), [fen]);
  const [selection, setSelection] = useState(null);
  const [promotion, setPromotion] = useState(null);
  const selected = playable && selection?.fen === fen ? selection.square : null;
  const pendingPromotion = playable && promotion?.fen === fen ? promotion : null;
  const ownSide = color[0];
  const otherSide = color === "white" ? "black" : "white";

  function select(square) {
    setSelection({ fen, square });
  }

  function attempt(from, to) {
    const matches = legalMoves.filter((uci) => uci.startsWith(from + to));
    if (!matches.length) {
      onIllegal("Lance ilegal para a posição atual.");
      return;
    }
    if (matches[0].length === 5) {
      setPromotion({ fen, from, to, moves: matches });
      return;
    }
    commit(matches[0]);
  }

  function commit(uci) {
    select(null);
    setPromotion(null);
    // Usa a notação local no indicador de espera; o FEN vem da API.
    const next = new Chess(fen);
    try {
      const move = next.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      onMove({ uci, san: move.san });
    } catch {
      onIllegal("Lance ilegal para a posição atual.");
    }
  }

  function clickSquare(square) {
    if (!playable || pendingPromotion) return;
    if (square === selected) select(null);
    else if (board.get(square)?.color === ownSide) select(square);
    else if (selected) attempt(selected, square);
  }

  const squareStyles = {};
  const checkedKing = board.inCheck() && board.board().flat()
    .find((piece) => piece?.type === "k" && piece.color === board.turn());
  for (const square of [lastMove?.slice(0, 2), lastMove?.slice(2, 4)].filter(Boolean)) {
    squareStyles[square] = { backgroundColor: "rgba(228, 208, 106, 0.40)" };
  }
  if (selected) {
    squareStyles[selected] = { ...squareStyles[selected], boxShadow: "inset 0 0 0 4px #d7f5aa" };
    for (const uci of legalMoves.filter((move) => move.startsWith(selected))) {
      const square = uci.slice(2, 4);
      squareStyles[square] = {
        ...squareStyles[square],
        backgroundImage: board.get(square)
          ? "radial-gradient(transparent 56%, #16372eaa 59%, #16372eaa 69%, transparent 72%)"
          : "radial-gradient(circle, #16372ea8 19%, transparent 21%)",
      };
    }
  }
  if (checkedKing) {
    const square = checkedKing.square;
    squareStyles[square] = { ...squareStyles[square], backgroundColor: "rgba(207, 59, 76, 0.72)" };
  }

  const interaction = playable && !pendingPromotion;
  const arrows = visuals ? [tip ? arrow(tip.uci, "#25834c") : arrow(lastMove, "rgba(67, 86, 151, 0.65)")].filter(Boolean) : [];
  return (
    <section className="play-board board-column" aria-label="Tabuleiro da partida">
      <Player player={{ nome: "Stockfish" }} color={otherSide} showRating={false} />
      <div className="board-frame" data-fen={fen} data-orientation={color}>
        <Chessboard options={{
          id: "play-board",
          position: fen,
          boardOrientation: color,
          allowDragging: interaction,
          allowDrawingArrows: false,
          clearArrowsOnClick: false,
          animationDurationInMs: 180,
          ...BOARD_COLORS,
          arrows,
          squareStyles,
          canDragPiece: ({ piece }) => interaction && piece.pieceType[0] === ownSide,
          onPieceDrag: ({ square }) => select(square),
          onSquareClick: ({ square }) => clickSquare(square),
          onPieceDrop: ({ sourceSquare, targetSquare }) => {
            if (interaction && targetSquare && sourceSquare !== targetSquare) attempt(sourceSquare, targetSquare);
            return false;
          },
        }} />
        {pendingPromotion && (
          <div className="play-promotion">
            <div className="panel" role="group" aria-label="Promoção de peão">
              <h3>Promover peão</h3>
              <div className="play-promotion-choices">
                {pendingPromotion.moves.map((uci, index) => {
                  const type = uci[4];
                  const Piece = defaultPieces[ownSide + type.toUpperCase()];
                  return (
                    <button key={uci} className="button secondary" type="button"
                      autoFocus={index === 0} onClick={() => commit(uci)}>
                      <Piece />
                      {PIECE_NAMES[type]}
                    </button>
                  );
                })}
              </div>
              <button className="text-button" type="button" onClick={() => setPromotion(null)}>
                Cancelar promoção
              </button>
            </div>
          </div>
        )}
      </div>
      <Player player={{ nome: "Você" }} color={color} showRating={false} />
    </section>
  );
}
