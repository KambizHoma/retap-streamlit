from __future__ import annotations
import math, random
from dataclasses import dataclass, field
from typing import Dict, Tuple
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import IsolationForest

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "transactions_log.csv"

def ensure_log_file() -> Path:
    if not LOG_FILE.exists():
        LOG_FILE.write_text("ts,sender,receiver,amount,hour,score\n")
    return LOG_FILE

@dataclass
class TxSimulator:
    seed: int = 42
    tx_per_second: int = 10
    num_senders: int = 50
    num_receivers: int = 50
    burst_prob: float = 0.05
    anomaly_prob: float = 0.02

    def __post_init__(self):
        random.seed(self.seed)
        np.random.seed(self.seed)
        self.sender_ids = [f"S{str(i).zfill(3)}" for i in range(self.num_senders)]
        self.receiver_ids = [f"R{str(i).zfill(3)}" for i in range(self.num_receivers)]
        self._t = 0

    def _base_amount(self, hour: int) -> float:
        base = 50 + 30 * math.sin(hour / 24 * 2 * math.pi)
        noise = np.random.lognormal(mean=3.3, sigma=0.4)
        return max(1.0, base + 0.1 * noise)

    def _maybe_anomaly(self, amt: float) -> float:
        if random.random() < self.anomaly_prob:
            factor = random.choice([5, 10, 0.2])
            return amt * factor
        return amt

    def generate_batch(self, n: int = 10) -> pd.DataFrame:
        now = pd.Timestamp.utcnow()
        rows = []
        for _ in range(n):
            self._t += 1
            sender = random.choice(self.sender_ids)
            receiver = random.choice(self.receiver_ids)
            hour = int((now.hour + (self._t % 60) // 60) % 24)
            amt = self._base_amount(hour)
            if random.random() < self.burst_prob:
                amt *= np.random.uniform(2, 4)
            amt = self._maybe_anomaly(amt)
            rows.append({"ts": now.isoformat(), "sender": sender, "receiver": receiver, "amount": round(float(amt), 2), "hour": hour})
        return pd.DataFrame(rows)

@dataclass
class Featureizer:
    means: Dict[str, float] = field(default_factory=dict)
    vars: Dict[str, float] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)

    def transform_row(self, row) -> Tuple[Dict[str, float], Dict[str, object]]:
        sender = row.sender
        amt = float(row.amount)
        hour = int(row.hour)
        n = self.counts.get(sender, 0) + 1
        mean = self.means.get(sender, 0.0)
        var = self.vars.get(sender, 1.0)
        delta = amt - mean
        mean += delta / n
        m2 = var * (n - 1) + delta * (amt - mean)
        var = m2 / max(1, n - 1)
        self.counts[sender] = n
        self.means[sender] = mean
        self.vars[sender] = max(var, 1e-6)
        z = (amt - mean) / math.sqrt(self.vars[sender])
        x = {"amt": amt, "hour": hour, "sender_count": float(n), "sender_amt_mean": mean, "sender_amt_z": float(z)}
        meta = {"ts": row.ts, "sender": sender, "receiver": row.receiver, "amount": amt, "hour": hour}
        return x, meta

@dataclass
class OnlineAnomalyModel:
    model: IsolationForest = field(default_factory=lambda: IsolationForest(contamination=0.15, random_state=42))
    buffer: list = field(default_factory=list)
    buffer_size: int = 100
    trained: bool = False
    score_mean: float = 0.0
    score_std: float = 1.0
    score_count: int = 0

    def score(self, features: Dict[str, float]) -> float:
        feature_array = np.array([[features["amt"], features["hour"], features["sender_count"], features["sender_amt_mean"], features["sender_amt_z"]]])
        self.buffer.append(feature_array[0])
        if len(self.buffer) >= self.buffer_size and not self.trained:
            X = np.array(self.buffer)
            self.model.fit(X)
            self.trained = True
        if self.trained:
            raw_score = self.model.score_samples(feature_array)[0]
            self.score_count += 1
            delta = raw_score - self.score_mean
            self.score_mean += delta / self.score_count
            delta2 = raw_score - self.score_mean
            self.score_std = math.sqrt((self.score_std ** 2 * (self.score_count - 1) + delta * delta2) / self.score_count) if self.score_count > 1 else 1.0
            z_score = (raw_score - self.score_mean) / (self.score_std + 1e-6) if self.score_std > 0 else 0
            base_score = 1 / (1 + math.exp(z_score * 2))
            anomaly_score = base_score * 0.8
            return float(max(0.0, min(1.0, anomaly_score)))
        else:
            return 0.25