from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskLimits(BaseModel):
    max_position_pct: float = 0.10
    max_total_exposure_pct: float = 0.90
    max_daily_loss_pct: float = 0.03
    max_single_trade_usd: float = 1000.0
    min_trade_usd: float = 10.0
    max_open_positions: int = 20
    default_stop_loss_pct: float = 5.0
    default_take_profit_pct: float = 15.0
    max_leverage: float = 1.0


class AggressiveRiskLimits(RiskLimits):
    """Medium/high risk, no leverage.

    max_single_trade_usd is a safety guard above the sizing logic.
    calculate_position_size() caps at 8% concentration (strong), so this
    limit only fires on portfolios >$62K.  Keep it well above realistic
    sizing output to avoid silent rejections.
    """
    max_position_pct: float = 0.20
    max_total_exposure_pct: float = 0.95
    max_single_trade_usd: float = 5000.0
    min_trade_usd: float = 50.0
    max_daily_loss_pct: float = 0.05
    default_stop_loss_pct: float = 8.0
    default_take_profit_pct: float = 20.0
    max_leverage: float = 1.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    etoro_api_key: str
    etoro_user_key_real: str
    etoro_user_key_demo: str
    trading_mode: str = "demo"
    db_path: str = str(Path(__file__).parent / "data" / "etoro.db")
    risk: RiskLimits = RiskLimits()

    # External news/data API keys (optional — leave empty to skip)
    finnhub_api_key: str = ""
    marketaux_api_key: str = ""
    fmp_api_key: str = ""

    @property
    def user_key(self) -> str:
        if self.trading_mode == "real":
            return self.etoro_user_key_real
        return self.etoro_user_key_demo

    @property
    def api_base(self) -> str:
        return "https://public-api.etoro.com"

    @property
    def mode_prefix(self) -> str:
        """Path prefix for demo vs real trading endpoints."""
        return "demo/" if self.trading_mode == "demo" else ""


settings = Settings()
