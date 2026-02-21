import unittest

from app.services.rank import mmr_to_rank


class MmrToRankTests(unittest.TestCase):
    def test_queen_rank_formatting(self) -> None:
        self.assertEqual(mmr_to_rank(3380, queen_rank=42), "Queen#42")
        self.assertEqual(mmr_to_rank(3600, queen_rank=None), "Queen")

    def test_threshold_boundaries_across_all_leagues(self) -> None:
        # exact threshold, threshold-1 and midpoints for each league
        cases: list[tuple[int, str]] = [
            # Queen / King
            (3380, "Queen"),
            (3379, "King"),
            (3340, "King"),
            # King / Rook
            (3300, "King"),
            (3299, "Rook-9"),
            # Rook
            (3220, "Rook-9"),
            (3219, "Rook-8"),
            (2860, "Rook-4"),
            # Bishop
            (2500, "Bishop-9"),
            (2499, "Bishop-8"),
            (2140, "Bishop-4"),
            # Knight
            (1780, "Knight-9"),
            (1779, "Knight-8"),
            (1420, "Knight-4"),
            # Pawn
            (1060, "Pawn-9"),
            (1059, "Pawn-8"),
            (780, "Pawn-5"),
            (500, "Pawn-2"),
            (499, "Pawn-1"),
            (420, "Pawn-1"),
            (419, "Pawn-1"),
        ]

        for mmr, expected in cases:
            with self.subTest(mmr=mmr, expected=expected):
                self.assertEqual(mmr_to_rank(mmr), expected)


if __name__ == "__main__":
    unittest.main()
