from app.models.user import Basket


MMR_THRESHOLDS: list[tuple[str, int]] = [
    ("Queen", 3380),
    ("King", 3300),
    ("Rook-9", 3220),
    ("Rook-1", 2580),
    ("Bishop-9", 2500),
    ("Bishop-1", 1860),
    ("Knight-9", 1780),
    ("Knight-1", 1140),
    ("Pawn-9", 1060),
    ("Pawn-1", 0),
]


def mmr_to_rank(mmr: int, queen_rank: int | None = None) -> str:
    # Конвертируем MMR в текстовый ранг.
    for title, threshold in MMR_THRESHOLDS:
        if mmr >= threshold:
            if title == "Queen" and queen_rank:
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
