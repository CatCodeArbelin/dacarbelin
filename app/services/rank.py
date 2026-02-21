from app.models.user import Basket


MMR_THRESHOLDS: list[tuple[str, int]] = [
    ("Queen", 3380),
    ("King", 3300),
    ("Rook-9", 3220),
    ("Rook-8", 3140),
    ("Rook-7", 3060),
    ("Rook-6", 2980),
    ("Rook-5", 2900),
    ("Rook-4", 2820),
    ("Rook-3", 2740),
    ("Rook-2", 2660),
    ("Rook-1", 2580),
    ("Bishop-9", 2500),
    ("Bishop-8", 2420),
    ("Bishop-7", 2340),
    ("Bishop-6", 2260),
    ("Bishop-5", 2180),
    ("Bishop-4", 2100),
    ("Bishop-3", 2020),
    ("Bishop-2", 1940),
    ("Bishop-1", 1860),
    ("Knight-9", 1780),
    ("Knight-8", 1700),
    ("Knight-7", 1620),
    ("Knight-6", 1540),
    ("Knight-5", 1460),
    ("Knight-4", 1380),
    ("Knight-3", 1300),
    ("Knight-2", 1220),
    ("Knight-1", 1140),
    ("Pawn-9", 1060),
    ("Pawn-8", 980),
    ("Pawn-7", 900),
    ("Pawn-6", 820),
    ("Pawn-5", 740),
    ("Pawn-4", 660),
    ("Pawn-3", 580),
    ("Pawn-2", 500),
    ("Pawn-1", 420),
]


def mmr_to_rank(mmr: int, queen_rank: int | None = None) -> str:
    # Конвертируем MMR в текстовый ранг.
    for title, threshold in MMR_THRESHOLDS:
        if mmr >= threshold:
            if title == "Queen" and queen_rank is not None:
                return f"Queen#{queen_rank}"
            return title
    return "Pawn-1"


def pick_basket(highest_rank: str, current_rank: str) -> str:
    # Назначаем корзину по правилам турнира.
    if current_rank.startswith("Queen#"):
        try:
            place = int(current_rank.replace("Queen#", ""))
            if 1 <= place <= 100:
                return Basket.QUEEN_TOP.value
        except ValueError:
            pass
    if highest_rank.startswith("Queen"):
        return Basket.QUEEN.value
    if highest_rank.startswith("King"):
        return Basket.KING.value
    if highest_rank.startswith("Rook"):
        return Basket.ROOK.value
    if highest_rank.startswith("Bishop"):
        return Basket.BISHOP.value
    return Basket.LOW_RANK.value
