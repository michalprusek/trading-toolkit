from __future__ import annotations

from dataclasses import dataclass
from config import settings, RiskLimits
from src.portfolio.manager import get_portfolio
from src.storage.repositories import TradeLogRepo


@dataclass
class RiskCheckResult:
    passed: bool
    violations: list[str]
    warnings: list[str]

    @property
    def summary(self) -> str:
        if self.passed:
            msg = "PASSED"
            if self.warnings:
                msg += f" with {len(self.warnings)} warning(s)"
            return msg
        return f"REJECTED: {'; '.join(self.violations)}"


def check_trade(
    symbol: str,
    amount: float,
    direction: str = "BUY",
    leverage: float = 1.0,
    limits_override: RiskLimits | None = None,
) -> RiskCheckResult:
    limits = limits_override or settings.risk
    violations: list[str] = []
    warnings: list[str] = []

    # 1. Trade size limits
    if amount < limits.min_trade_usd:
        violations.append(f"Amount ${amount} below minimum ${limits.min_trade_usd}")
    if amount > limits.max_single_trade_usd:
        violations.append(f"Amount ${amount} exceeds maximum ${limits.max_single_trade_usd}")

    # 2. Leverage limit
    if leverage > limits.max_leverage:
        violations.append(f"Leverage {leverage}x exceeds maximum {limits.max_leverage}x")

    # 3. Portfolio-level checks (fetch live data)
    try:
        portfolio = get_portfolio()
    except Exception as e:
        warnings.append(f"Could not fetch portfolio for risk check: {e}")
        return RiskCheckResult(passed=len(violations) == 0, violations=violations, warnings=warnings)

    # 4. Max open positions
    if len(portfolio.positions) >= limits.max_open_positions:
        violations.append(
            f"Already at max positions ({len(portfolio.positions)}/{limits.max_open_positions})"
        )

    # 5. Total exposure check
    total_value = portfolio.total_value
    if total_value > 0:
        current_exposure = portfolio.total_invested / total_value
        new_exposure = (portfolio.total_invested + amount) / total_value
        if new_exposure > limits.max_total_exposure_pct:
            violations.append(
                f"Total exposure would be {new_exposure:.1%} (max {limits.max_total_exposure_pct:.0%})"
            )
        if new_exposure > 0.80:
            warnings.append(f"High exposure: {new_exposure:.1%} of portfolio")

    # 6. Single position concentration
    if total_value > 0:
        position_pct = amount / total_value
        if position_pct > limits.max_position_pct:
            violations.append(
                f"Position would be {position_pct:.1%} of portfolio (max {limits.max_position_pct:.0%})"
            )

    # 7. Daily loss check
    try:
        trade_repo = TradeLogRepo()
        daily_stats = trade_repo.get_today_stats()
        daily_loss = daily_stats.get("realized_pnl", 0)
        if total_value > 0 and daily_loss < 0:
            daily_loss_pct = abs(daily_loss) / total_value
            if daily_loss_pct >= limits.max_daily_loss_pct:
                violations.append(
                    f"Daily loss {daily_loss_pct:.1%} exceeds limit {limits.max_daily_loss_pct:.0%}"
                )
    except Exception:
        pass

    # 9. CFD / leverage warnings
    if leverage > 1:
        warnings.append("Leveraged position: overnight fees will apply")
    if direction == "SELL":
        warnings.append("Short position: overnight fees will apply (CFD)")

    return RiskCheckResult(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )
