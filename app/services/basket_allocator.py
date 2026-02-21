"""Распределяет участников по корзинам и проверяет ограничения посева."""

from collections.abc import Mapping

from app.models.user import Basket

LIMITED_BASKET_RESERVES: dict[str, str] = {
    Basket.QUEEN.value: Basket.QUEEN_RESERVE.value,
    Basket.KING.value: Basket.KING_RESERVE.value,
    Basket.ROOK.value: Basket.ROOK_RESERVE.value,
    Basket.BISHOP.value: Basket.BISHOP_RESERVE.value,
    Basket.LOW_RANK.value: Basket.LOW_RANK_RESERVE.value,
}


def allocate_basket(target_basket: str, basket_counts: Mapping[str, int], limit: int = 8) -> str:
    """Возвращает итоговую корзину с учетом лимитов и reserve-корзин."""
    reserve_basket = LIMITED_BASKET_RESERVES.get(target_basket)
    if not reserve_basket:
        return target_basket

    current_count = basket_counts.get(target_basket, 0)
    if current_count >= limit:
        return reserve_basket
    return target_basket
