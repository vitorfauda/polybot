"""Calibration Engine - Adjusts AI probability estimates based on historical accuracy."""


class CalibrationEngine:
    """
    Tracks how well our probability estimates match reality.
    If Claude says 70% but outcomes happen 55% of the time, we adjust.
    """

    def __init__(self):
        self.buckets = {}  # {bucket: {"total": n, "correct": n}}

    def record(self, predicted_prob: float, was_correct: bool):
        """Record a prediction result for calibration tracking."""
        bucket = round(predicted_prob * 10) / 10  # round to nearest 10%
        if bucket not in self.buckets:
            self.buckets[bucket] = {"total": 0, "correct": 0}
        self.buckets[bucket]["total"] += 1
        if was_correct:
            self.buckets[bucket]["correct"] += 1

    def get_adjustment(self, predicted_prob: float) -> float:
        """Get calibrated probability based on historical accuracy."""
        bucket = round(predicted_prob * 10) / 10
        if bucket in self.buckets and self.buckets[bucket]["total"] >= 5:
            actual_rate = self.buckets[bucket]["correct"] / self.buckets[bucket]["total"]
            # Blend: 70% model prediction, 30% historical calibration
            return 0.7 * predicted_prob + 0.3 * actual_rate
        return predicted_prob  # not enough data, return as-is

    def load_from_trades(self, trades: list[dict]):
        """Load calibration data from historical trades."""
        for trade in trades:
            if trade.get("pnl") is None:
                continue  # unresolved
            prob = trade.get("price", 0.5)
            won = trade.get("pnl", 0) > 0
            self.record(prob, won)

    def get_report(self) -> dict:
        """Generate calibration report."""
        report = {}
        for bucket, data in sorted(self.buckets.items()):
            if data["total"] > 0:
                actual = data["correct"] / data["total"]
                report[f"{bucket*100:.0f}%"] = {
                    "predicted": bucket,
                    "actual": round(actual, 3),
                    "samples": data["total"],
                    "gap": round(bucket - actual, 3),
                }
        return report
