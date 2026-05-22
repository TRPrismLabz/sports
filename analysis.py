"""
EV Analysis Engine — Sports Betting (NRL / NBA / AFL)
Multi-signal logit aggregation: ELO power ratings, Poisson model,
line movement detection, public fade, and prop stat models.
Markets matched to Sportsbet / Ladbrokes AU offerings.
"""
import numpy as np
from scipy import stats
from scipy.stats import poisson as sp_poisson
from config import BETAS


class SportsAnalysisEngine:

    def __init__(self):
        self.betas = BETAS

    # ── Main entry points ────────────────────────────────────────────────────

    def analyze_h2h(self, game: dict, bookmakers: list, stats_manager) -> list:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        sport = game.get("sport", "NRL")

        home_prices, away_prices = [], []
        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                for oc in mkt.get("outcomes", []):
                    p = float(oc.get("price", 0))
                    if p <= 1.0:
                        continue
                    if oc.get("name", "").lower() == home.lower():
                        home_prices.append(p)
                    elif oc.get("name", "").lower() == away.lower():
                        away_prices.append(p)

        if not home_prices:
            home_prices = [1.85]
        if not away_prices:
            away_prices = [1.95]

        best_home, best_away = max(home_prices), max(away_prices)
        raw_home = 1 / np.mean(home_prices)
        raw_away = 1 / np.mean(away_prices)
        total = raw_home + raw_away
        cons_home = raw_home / total
        cons_away = raw_away / total

        poi_home, poi_away = self._elo_win_prob(sport, home, away, stats_manager)
        results = []
        for team, cons_prob, model_prob, best_price in [
            (home, cons_home, poi_home, best_home),
            (away, cons_away, poi_away, best_away),
        ]:
            lm = self._line_movement(home_prices if team == home else away_prices)
            fade = self._public_fade(cons_prob)
            signals = {
                "consensus_market": {"adjustment": 0.0, "prob": round(cons_prob, 4)},
                "elo_model":        {"adjustment": round(model_prob - cons_prob, 4)},
                "line_movement":    {"adjustment": round(lm, 4)},
                "public_fade":      {"adjustment": round(fade, 4)},
            }
            true_prob = self._logit_agg(cons_prob, signals)
            market_prob = 1 / best_price
            edge = true_prob - market_prob
            ev_pct = (true_prob * (best_price - 1) - (1 - true_prob)) * 100
            conf = self._confidence(signals, len(home_prices))
            results.append({
                "market_type": "h2h",
                "outcome": team,
                "player": None,
                "true_prob": round(true_prob, 4),
                "market_prob": round(market_prob, 4),
                "edge": round(edge, 4),
                "confidence": round(conf, 4),
                "best_price": round(best_price, 3),
                "ev_pct": round(ev_pct, 2),
                "signals": signals,
                "reasoning": self._h2h_reason(team, true_prob, market_prob, edge, fade, lm),
            })
        return results

    def analyze_totals(self, game: dict, bookmakers: list, stats_manager) -> list:
        sport = game.get("sport", "NRL")
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        lines = {}
        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "totals":
                    continue
                for oc in mkt.get("outcomes", []):
                    pt = oc.get("point")
                    if pt is None:
                        continue
                    key = (oc.get("name", "over").lower(), float(pt))
                    p = float(oc.get("price", 0))
                    if p > 1.0:
                        lines.setdefault(key, []).append(p)

        if not lines:
            mu = self._avg_total(sport)
            lines = {("over", mu): [1.90], ("under", mu): [1.90]}

        results = []
        for (direction, point), prices in lines.items():
            best_price = max(prices)
            market_prob = 1 / np.mean(prices)
            mu = self._expected_mu(sport, home, away, stats_manager)
            true_prob = self._poisson_total(direction, point, mu)
            signals = {
                "poisson_model":  {"adjustment": round(true_prob - market_prob, 4), "mu": round(mu, 1)},
                "line_movement":  {"adjustment": round(self._line_movement(prices), 4)},
            }
            edge = true_prob - (1 / best_price)
            ev_pct = (true_prob * (best_price - 1) - (1 - true_prob)) * 100
            results.append({
                "market_type": "totals",
                "outcome": f"{direction.upper()} {point}",
                "player": None,
                "true_prob": round(true_prob, 4),
                "market_prob": round(market_prob, 4),
                "edge": round(edge, 4),
                "confidence": round(self._confidence(signals, len(prices)), 4),
                "best_price": round(best_price, 3),
                "ev_pct": round(ev_pct, 2),
                "signals": signals,
                "reasoning": (
                    f"Poisson (μ={mu:.1f}) gives {true_prob:.1%} for "
                    f"{direction.upper()} {point}. Market: {market_prob:.1%}. "
                    f"Edge: {edge*100:+.1f}%."
                ),
            })
        return results

    def analyze_spreads(self, game: dict, bookmakers: list, stats_manager) -> list:
        sport = game.get("sport", "NRL")
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        lines = {}
        for bm in bookmakers:
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "spreads":
                    continue
                for oc in mkt.get("outcomes", []):
                    pt = oc.get("point")
                    if pt is None:
                        continue
                    key = (oc.get("name", "").lower(), float(pt))
                    p = float(oc.get("price", 0))
                    if p > 1.0:
                        lines.setdefault(key, []).append(p)

        if not lines:
            sp = self._expected_spread(sport, home, away, stats_manager)
            lines = {(home.lower(), -sp): [1.90], (away.lower(), sp): [1.90]}

        results = []
        for (team_lower, point), prices in lines.items():
            best_price = max(prices)
            market_prob = 1 / np.mean(prices)
            true_prob = self._spread_prob(sport, home, away, team_lower, point, stats_manager)
            signals = {
                "spread_model":  {"adjustment": round(true_prob - market_prob, 4), "handicap": point},
                "line_movement": {"adjustment": round(self._line_movement(prices), 4)},
            }
            edge = true_prob - (1 / best_price)
            ev_pct = (true_prob * (best_price - 1) - (1 - true_prob)) * 100
            results.append({
                "market_type": "spreads",
                "outcome": f"{team_lower.title()} {point:+.1f}",
                "player": None,
                "true_prob": round(true_prob, 4),
                "market_prob": round(market_prob, 4),
                "edge": round(edge, 4),
                "confidence": round(self._confidence(signals, len(prices)), 4),
                "best_price": round(best_price, 3),
                "ev_pct": round(ev_pct, 2),
                "signals": signals,
                "reasoning": (
                    f"Model: {true_prob:.1%} vs market: {market_prob:.1%} "
                    f"for {team_lower.title()} {point:+.1f}. "
                    f"Edge: {edge*100:+.1f}%."
                ),
            })
        return results

    def analyze_props(self, game: dict, prop_data: list, stats_manager) -> list:
        """Analyze player/team prop markets."""
        sport = game.get("sport", "NRL")
        cfg_all = self._prop_configs(sport)
        results = []
        for prop in prop_data:
            mkey = prop.get("market_key", "")
            player = prop.get("player", "Unknown Player")
            direction = prop.get("direction", "over")
            line = float(prop.get("line", 0))
            prices = prop.get("prices", [1.90])
            
            cfg = cfg_all.get(mkey, {"label": mkey, "cm": 0.70})
            
            # Fetch dynamic live average and standard deviation
            live_stat = stats_manager.get_player_stat(sport, player, mkey)
            if live_stat.get("avg") > 0:
                p_avg = live_stat["avg"]
                p_std = live_stat["std"]
            else:
                # Fallback to defaults
                p_avg = cfg.get("avg", line)
                p_std = cfg.get("std", max(line * 0.35, 1.0))

            best_price = max(prices) if prices else 1.90
            market_prob = 1 / np.mean(prices) if prices else 0.5
            true_prob = self._prop_prob(direction, line, p_avg, p_std)

            signals = {
                "stat_model":        {"adjustment": round(true_prob - market_prob, 4), "avg": p_avg, "line": line},
                "market_efficiency": {"adjustment": self._prop_eff(len(prices))},
            }
            edge = true_prob - (1 / best_price)
            ev_pct = (true_prob * (best_price - 1) - (1 - true_prob)) * 100
            conf = self._confidence(signals, len(prices)) * cfg.get("cm", 0.70)
            results.append({
                "market_type": mkey,
                "market_label": cfg["label"],
                "outcome": f"{direction.upper()} {line}",
                "player": player,
                "true_prob": round(true_prob, 4),
                "market_prob": round(market_prob, 4),
                "edge": round(edge, 4),
                "confidence": round(conf, 4),
                "best_price": round(best_price, 3),
                "ev_pct": round(ev_pct, 2),
                "signals": signals,
                "reasoning": (
                    f"{player} {direction.upper()} {line} {cfg['label']}. "
                    f"Season avg: {p_avg}. Model: {true_prob:.1%}, "
                    f"Market: {market_prob:.1%}. EV: {ev_pct:+.1f}%."
                ),
            })
        return results

    # ── Statistical models ───────────────────────────────────────────────────

    def _elo_win_prob(self, sport, home, away, stats_manager):
        hr = stats_manager.get_team_rating(sport, home)
        ar = stats_manager.get_team_rating(sport, away)
        ha = {"NRL": 50, "NBA": 30, "AFL": 45}.get(sport, 35)
        p_home = 1 / (1 + 10 ** -((hr + ha - ar) / 400))
        return round(p_home, 4), round(1 - p_home, 4)

    def _poisson_total(self, direction, line, mu):
        if direction == "over":
            return max(0.05, min(0.95, float(1 - sp_poisson.cdf(int(line), mu))))
        return max(0.05, min(0.95, float(sp_poisson.cdf(int(line) - 1, mu))))

    def _spread_prob(self, sport, home, away, team_lower, point, stats_manager):
        hr = stats_manager.get_team_rating(sport, home)
        ar = stats_manager.get_team_rating(sport, away)
        ha = {"NRL": 3.5, "NBA": 3.0, "AFL": 6.0}.get(sport, 3.0)
        std = {"NRL": 14.0, "NBA": 12.0, "AFL": 30.0}.get(sport, 14.0)
        exp_margin = (hr - ar) / 60 + ha
        cover = (exp_margin + point) if team_lower == home.lower() else (-exp_margin + point)
        return max(0.05, min(0.95, float(stats.norm.cdf(cover / std))))

    def _prop_prob(self, direction, line, avg, std):
        if std <= 0:
            std = 1.0
        if direction == "over":
            return max(0.05, min(0.95, float(1 - stats.norm.cdf(line, avg, std))))
        return max(0.05, min(0.95, float(stats.norm.cdf(line, avg, std))))

    def _expected_mu(self, sport, home, away, stats_manager):
        base = {"NRL": 44.5, "NBA": 227.0, "AFL": 168.0}.get(sport, 44.5)
        hr = stats_manager.get_team_rating(sport, home)
        ar = stats_manager.get_team_rating(sport, away)
        adj = ((hr + ar) - 3000) / 2000
        return base * (1 + adj * 0.08)

    def _avg_total(self, sport):
        return {"NRL": 44.5, "NBA": 227.5, "AFL": 166.5}.get(sport, 44.5)

    def _expected_spread(self, sport, home, away, stats_manager):
        hr = stats_manager.get_team_rating(sport, home)
        ar = stats_manager.get_team_rating(sport, away)
        diff = abs(hr - ar) / 60
        return round(max(1.5, diff), 1)

    def _line_movement(self, prices):
        if len(prices) < 2:
            return 0.0
        return round((max(prices) - min(prices)) / np.mean(prices) * 0.1, 4)

    def _public_fade(self, prob):
        if prob > 0.72:
            return round(-(prob - 0.72) * 0.15, 4)
        if prob < 0.28:
            return round((0.28 - prob) * 0.10, 4)
        return 0.0

    def _prop_eff(self, n_books):
        if n_books <= 2:
            return 0.03
        if n_books <= 4:
            return 0.01
        return 0.0

    def _logit_agg(self, market_prob, signals):
        p = max(0.01, min(0.99, market_prob))
        logit = float(np.log(p / (1 - p)))
        total_adj = sum(
            s.get("adjustment", 0) for s in signals.values() if isinstance(s, dict)
        )
        logit_est = self.betas["market"] * logit + total_adj * 1.5
        return float(1 / (1 + np.exp(-logit_est)))

    def _confidence(self, signals, n_books):
        return round(min(1.0, n_books / 6) * 0.6 + min(1.0, len(signals) / 4) * 0.4, 4)

    def _h2h_reason(self, team, tp, mp, edge, fade, lm):
        parts = [f"ELO model: {tp:.1%} win prob for {team}. Market: {mp:.1%}. Edge: {edge*100:+.1f}%."]
        if abs(fade) > 0.01:
            parts.append(f"Public betting bias (fade signal {fade*100:+.1f}%).")
        if abs(lm) > 0.015:
            parts.append("Sharp line movement detected.")
        if edge > 0.05:
            parts.append("STRONG EDGE — Kelly sizing recommended.")
        elif edge > 0.03:
            parts.append("Moderate edge — half Kelly recommended.")
        return " ".join(parts)

    def _prop_configs(self, sport):
        if sport == "NRL":
            return {
                "player_tries":         {"label": "Tries Scored",        "avg": 0.65, "std": 0.55, "cm": 0.75},
                "player_first_try":     {"label": "First Try Scorer",    "avg": 0.65, "std": 0.55, "cm": 0.65},
                "player_anytime_try":   {"label": "Anytime Try Scorer",  "avg": 0.65, "std": 0.55, "cm": 0.75},
                "player_points":        {"label": "Points Scored",       "avg": 8.5,  "std": 5.5,  "cm": 0.72},
                "player_assists":       {"label": "Try Assists",         "avg": 0.8,  "std": 0.65, "cm": 0.68},
                "player_kicks":         {"label": "Kicks in Play",       "avg": 22.0, "std": 8.5,  "cm": 0.73},
                "player_tackles":       {"label": "Tackles",             "avg": 28.0, "std": 10.5, "cm": 0.73},
                "player_runs":          {"label": "Runs",                "avg": 12.5, "std": 5.5,  "cm": 0.71},
                "team_tries":           {"label": "Team Tries",          "avg": 4.2,  "std": 1.9,  "cm": 0.76},
                "half_totals":          {"label": "Half-Time Total",     "avg": 22.5, "std": 9.0,  "cm": 0.76},
                "winning_margin":       {"label": "Winning Margin",      "avg": 12.0, "std": 10.0, "cm": 0.70},
            }
        elif sport == "NBA":
            return {
                "player_points":                    {"label": "Points",          "avg": 22.0, "std": 8.0,  "cm": 0.83},
                "player_rebounds":                  {"label": "Rebounds",        "avg": 7.5,  "std": 3.5,  "cm": 0.81},
                "player_assists":                   {"label": "Assists",         "avg": 5.5,  "std": 3.0,  "cm": 0.81},
                "player_threes":                    {"label": "3-Pointers Made", "avg": 2.5,  "std": 1.5,  "cm": 0.76},
                "player_blocks":                    {"label": "Blocks",          "avg": 1.2,  "std": 0.9,  "cm": 0.73},
                "player_steals":                    {"label": "Steals",          "avg": 1.1,  "std": 0.8,  "cm": 0.73},
                "player_turnovers":                 {"label": "Turnovers",       "avg": 2.5,  "std": 1.5,  "cm": 0.71},
                "player_points_rebounds_assists":   {"label": "PRA",             "avg": 35.0, "std": 10.0, "cm": 0.79},
                "player_points_rebounds":           {"label": "P+R",             "avg": 29.0, "std": 8.0,  "cm": 0.79},
                "player_points_assists":            {"label": "P+A",             "avg": 27.0, "std": 8.0,  "cm": 0.79},
                "player_first_basket":              {"label": "First Basket",    "avg": 0.5,  "std": 0.4,  "cm": 0.65},
                "half_totals":                      {"label": "Half Total",      "avg": 114.0,"std": 12.0, "cm": 0.79},
                "quarter_totals":                   {"label": "Quarter Total",   "avg": 57.0, "std": 8.0,  "cm": 0.76},
            }
        else:  # AFL
            return {
                "player_disposals":              {"label": "Disposals",              "avg": 22.0, "std": 7.0,  "cm": 0.83},
                "player_kicks":                  {"label": "Kicks",                  "avg": 13.0, "std": 5.0,  "cm": 0.81},
                "player_handballs":              {"label": "Handballs",              "avg": 9.0,  "std": 4.0,  "cm": 0.76},
                "player_marks":                  {"label": "Marks",                  "avg": 5.5,  "std": 3.0,  "cm": 0.76},
                "player_goals":                  {"label": "Goals",                  "avg": 1.5,  "std": 1.2,  "cm": 0.76},
                "player_behinds":                {"label": "Behinds",               "avg": 1.0,  "std": 0.9,  "cm": 0.72},
                "player_tackles":                {"label": "Tackles",               "avg": 4.5,  "std": 2.5,  "cm": 0.79},
                "player_hitouts":                {"label": "Hit-Outs",              "avg": 22.0, "std": 9.0,  "cm": 0.76},
                "player_clearances":             {"label": "Clearances",            "avg": 5.0,  "std": 2.8,  "cm": 0.76},
                "player_inside_50s":             {"label": "Inside 50s",            "avg": 5.5,  "std": 3.0,  "cm": 0.74},
                "player_contested_possessions":  {"label": "Contested Possessions", "avg": 10.0, "std": 4.0,  "cm": 0.77},
                "player_anytime_goal":           {"label": "Anytime Goalkicker",    "avg": 1.5,  "std": 1.2,  "cm": 0.73},
                "player_first_goal":             {"label": "First Goalkicker",      "avg": 1.5,  "std": 1.2,  "cm": 0.66},
                "player_score_involvements":     {"label": "Score Involvements",    "avg": 6.0,  "std": 3.0,  "cm": 0.74},
                "player_goal_assists":           {"label": "Goal Assists",          "avg": 1.5,  "std": 1.1,  "cm": 0.71},
                "half_totals":                   {"label": "Half-Time Total",       "avg": 84.0, "std": 20.0, "cm": 0.79},
                "quarter_totals":                {"label": "Quarter Total",         "avg": 42.0, "std": 12.0, "cm": 0.76},
                "winning_margin":                {"label": "Winning Margin",        "avg": 28.0, "std": 22.0, "cm": 0.71},
            }
