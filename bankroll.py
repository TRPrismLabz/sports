"""
Bankroll Manager — Kelly Criterion sizing for sports betting.
"""
from config import DEFAULT_KELLY_FRACTION, MAX_SINGLE_POSITION_PCT, MAX_TOTAL_EXPOSURE_PCT


class BankrollManager:
    def __init__(self, bankroll=1000.0, kelly_fraction=DEFAULT_KELLY_FRACTION):
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.max_single = MAX_SINGLE_POSITION_PCT
        self.max_total = MAX_TOTAL_EXPOSURE_PCT

    def kelly_size(self, true_prob: float, decimal_odds: float) -> dict:
        """
        Kelly Criterion for decimal odds.
        f* = (b*p - q) / b  where b = decimal_odds - 1
        """
        if decimal_odds <= 1.0 or true_prob <= 0 or true_prob >= 1:
            return self._no_bet("Invalid inputs")

        b = decimal_odds - 1.0
        p = true_prob
        q = 1 - p
        full_kelly = (b * p - q) / b

        if full_kelly <= 0:
            return self._no_bet("Negative EV — no edge")

        adj_kelly = min(full_kelly * self.kelly_fraction, self.max_single)
        bet_amount = adj_kelly * self.bankroll
        if bet_amount < 1.0:
            return self._no_bet("Bet too small")

        profit_if_win = bet_amount * b
        ev = p * profit_if_win - q * bet_amount
        ev_pct = ev / bet_amount * 100

        return {
            "should_bet": True,
            "full_kelly_pct": round(full_kelly * 100, 2),
            "adj_kelly_pct": round(adj_kelly * 100, 2),
            "bet_amount": round(bet_amount, 2),
            "bankroll_pct": round(adj_kelly * 100, 2),
            "ev_pct": round(ev_pct, 2),
            "profit_if_win": round(profit_if_win, 2),
            "decimal_odds": round(decimal_odds, 3),
        }

    def _no_bet(self, reason):
        return {
            "should_bet": False, "reason": reason,
            "bet_amount": 0, "ev_pct": 0,
            "adj_kelly_pct": 0, "full_kelly_pct": 0,
            "bankroll_pct": 0, "profit_if_win": 0,
            "decimal_odds": 0,
        }

    def update_bankroll(self, amount):
        self.bankroll = float(amount)

    def set_kelly_fraction(self, fraction):
        self.kelly_fraction = max(0.1, min(1.0, float(fraction)))

    def summary(self):
        return {
            "bankroll": round(self.bankroll, 2),
            "kelly_fraction": self.kelly_fraction,
            "kelly_mode": f"{self.kelly_fraction:.0%} Kelly",
            "max_single_bet": round(self.bankroll * self.max_single, 2),
        }
