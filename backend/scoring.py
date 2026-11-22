"""Teknik ve bilanco puanlari icin ortak, seffaf puan karti."""
from __future__ import annotations

from typing import Any


class ScoreCard:
    """
    Puanlari sadece MEVCUT verilerle hesaplar ve her kalemin katkisini saklar.

    * Puani None olan kalem "eksik veri" sayilir: puan kazandirmaz, kaybettirmez; o kalemin
      agirligi toplamdan cikarilir ve 'veri kapsami' ayrica raporlanir.
    * `breakdown()` arayuzde "ROIC: 15/15, Degerleme: 7/15" gibi gosterilecek dokumu verir.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, label: str, points: float | None, weight: float, key: str | None = None,
            detail: str | None = None) -> None:
        if weight <= 0:
            return
        pts = None if points is None else max(0.0, min(float(weight), float(points)))
        self.items.append({"key": key or label, "label": label, "points": pts, "weight": float(weight),
                           "detail": detail})

    def add_signal(self, label: str, signal: float | None, weight: float, key: str | None = None,
                   detail: str | None = None) -> None:
        """signal 0..1 araliginda (1 = tam puan)."""
        self.add(label, None if signal is None else signal * weight, weight, key, detail)

    @property
    def total_weight(self) -> float:
        return sum(i["weight"] for i in self.items)

    @property
    def scored_weight(self) -> float:
        return sum(i["weight"] for i in self.items if i["points"] is not None)

    @property
    def points(self) -> float:
        return sum(i["points"] for i in self.items if i["points"] is not None)

    @property
    def coverage(self) -> float:
        return (self.scored_weight / self.total_weight) if self.total_weight else 0.0

    @property
    def missing(self) -> list[str]:
        return [i["label"] for i in self.items if i["points"] is None]

    def score(self, penalty: float = 0.0) -> int | None:
        if self.scored_weight <= 0:
            return None
        return int(max(0, min(100, round(self.points / self.scored_weight * 100.0 - penalty))))

    def breakdown(self) -> list[dict[str, Any]]:
        """Her kalem: puan / agirlik ve 100'luk olcekteki katkisi."""
        sw = self.scored_weight or 1.0
        out = []
        for i in self.items:
            out.append({
                "key": i["key"],
                "label": i["label"],
                "points": None if i["points"] is None else round(i["points"], 1),
                "max": round(i["weight"], 1),
                "contribution": None if i["points"] is None else round(i["points"] / sw * 100.0, 1),
                "detail": i["detail"],
            })
        return out
