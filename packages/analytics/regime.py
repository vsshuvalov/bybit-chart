"""
Orderflow regime detector (Roadmap §9.1 Étап 6).

Агрегирует все book-derived features и классифицирует текущий режим рынка.
"""

from collections import defaultdict
from typing import Any

from contracts.regime import MarketRegime, OrderflowFeature, RegimeState, FeatureImportance, RegimeAnalysis


class RegimeDetector:
    """Детектор режима рынка на основе orderflow features.

    Usage:
        detector = RegimeDetector(
            symbol="BTCUSDT",
            window_ms=300000,  # 5 minutes
        )

        # Добавить features из различных детекторов
        detector.add_feature("obi", active=True, value=0.65, confidence=0.8)
        detector.add_feature("walls_bid", active=True, value=50000, confidence=0.9)
        detector.add_feature("absorption", active=False, confidence=0.3)

        # Вычислить текущий режим
        state = detector.compute_regime()
        print(f"Regime: {state.regime}, confidence: {state.regime_confidence}")

        # Получить feature importance
        analysis = detector.analyze()
        for fi in analysis.feature_importance:
            print(f"{fi.name}: {fi.importance:.2f}")
    """

    def __init__(
        self,
        symbol: str,
        window_ms: int = 300000,  # 5 minutes default
    ):
        """Инициализировать regime detector.

        Args:
            symbol: торговая пара
            window_ms: размер временного окна для анализа
        """
        self.symbol = symbol
        self.window_ms = window_ms
        self._features: dict[str, OrderflowFeature] = {}
        self._last_update_ms: int = 0

    def add_feature(
        self,
        name: str,
        active: bool,
        confidence: float,
        value: float | None = None,
        timestamp_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Добавить или обновить feature.

        Args:
            name: название feature (например, "walls_bid", "absorption")
            active: активна ли feature
            confidence: уверенность [0.0, 1.0]
            value: числовое значение (опционально)
            timestamp_ms: время обновления (default: текущее)
            metadata: дополнительные данные
        """
        import time
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)

        self._features[name] = OrderflowFeature(
            name=name,
            active=active,
            value=value,
            confidence=confidence,
            timestamp_ms=timestamp_ms,
            metadata=metadata or {},
        )
        self._last_update_ms = max(self._last_update_ms, timestamp_ms)

    def compute_regime(self) -> RegimeState:
        """Вычислить текущий режим рынка на основе активных features.

        Returns:
            RegimeState с классифицированным режимом
        """
        if not self._features:
            return RegimeState(
                symbol=self.symbol,
                regime=MarketRegime.UNKNOWN,
                regime_confidence=0.0,
                features=[],
                timestamp_ms=self._last_update_ms,
                window_ms=self.window_ms,
            )

        # Простая эвристика для классификации режима
        # В production это может быть ML-модель
        regime, confidence = self._classify_regime()

        return RegimeState(
            symbol=self.symbol,
            regime=regime,
            regime_confidence=confidence,
            features=list(self._features.values()),
            timestamp_ms=self._last_update_ms,
            window_ms=self.window_ms,
        )

    def analyze(self) -> RegimeAnalysis:
        """Полный анализ с feature importance.

        Returns:
            RegimeAnalysis с текущим состоянием и feature importance
        """
        state = self.compute_regime()
        importance = self._compute_feature_importance(state.regime)

        return RegimeAnalysis(
            state=state,
            feature_importance=importance,
            regime_history=[],  # TODO: track history
        )

    def _classify_regime(self) -> tuple[MarketRegime, float]:
        """Классифицировать режим на основе активных features.

        Returns:
            (MarketRegime, confidence)
        """
        # Подсчёт active features по категориям
        buying_pressure = 0.0
        selling_pressure = 0.0
        imbalance_score = 0.0
        wall_count = 0

        for feat in self._features.values():
            if not feat.active:
                continue

            # OBI/OFI влияют на buying/selling pressure
            if feat.name in ("obi", "ofi"):
                if feat.value is not None:
                    if feat.value > 0:
                        buying_pressure += feat.confidence
                    else:
                        selling_pressure += feat.confidence
                    imbalance_score += abs(feat.value) * feat.confidence

            # Walls (bid/ask) влияют на pressure
            if "walls" in feat.name:
                wall_count += 1
                if "bid" in feat.name or "bid" in feat.metadata.get("side", ""):
                    buying_pressure += feat.confidence * 0.5
                elif "ask" in feat.name or "ask" in feat.metadata.get("side", ""):
                    selling_pressure += feat.confidence * 0.5

            # Absorption влияет на pressure
            if feat.name == "absorption":
                side = feat.metadata.get("side", "")
                if side == "bid":
                    buying_pressure += feat.confidence * 0.7
                elif side == "ask":
                    selling_pressure += feat.confidence * 0.7

            # Liquidation cascades = высокая волатильность
            if feat.name == "liquidation_cascade":
                direction = feat.metadata.get("direction", "")
                if direction == "Buy":
                    buying_pressure += feat.confidence * 0.8
                elif direction == "Sell":
                    selling_pressure += feat.confidence * 0.8

        # Классификация на основе scores
        total_pressure = buying_pressure + selling_pressure

        if total_pressure < 0.3:
            # Низкая активность
            return MarketRegime.NEUTRAL, 0.5

        pressure_diff = buying_pressure - selling_pressure

        if abs(pressure_diff) < 0.5:
            # Balanced orderflow
            if wall_count >= 2:
                return MarketRegime.ACCUMULATION, 0.7
            return MarketRegime.NEUTRAL, 0.6

        # Directional pressure
        if pressure_diff > 0.5:
            # Strong buying
            if imbalance_score > 1.5:  # Повышен порог для MARKUP
                return MarketRegime.MARKUP, 0.8
            return MarketRegime.ACCUMULATION, 0.7
        else:
            # Strong selling
            if imbalance_score > 1.5:  # Повышен порог для MARKDOWN
                return MarketRegime.MARKDOWN, 0.8
            return MarketRegime.DISTRIBUTION, 0.7

    def _compute_feature_importance(self, regime: MarketRegime) -> list[FeatureImportance]:
        """Вычислить importance каждой feature для текущего режима.

        Args:
            regime: текущий режим

        Returns:
            Список FeatureImportance, отсортированный по importance
        """
        importance_list = []

        for feat in self._features.values():
            # Importance = насколько feature активна * её влияние на regime
            base_importance = feat.confidence if feat.active else 0.0

            # Contribution = направление влияния
            contribution = 0.0
            if feat.active and feat.value is not None:
                contribution = feat.value * feat.confidence

            importance_list.append(
                FeatureImportance(
                    name=feat.name,
                    importance=base_importance,
                    contribution=contribution,
                )
            )

        # Сортировать по importance (desc)
        importance_list.sort(key=lambda x: x.importance, reverse=True)
        return importance_list
