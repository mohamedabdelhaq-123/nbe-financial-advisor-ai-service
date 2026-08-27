from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketGatewaySettings(BaseSettings):
    """Configuration for the optional public-source gateway.

    Source base URLs intentionally have no code defaults. Docker supplies the
    public endpoints for local development; a deployment can replace any of
    them, or point the AI service at a different normalized gateway entirely.
    """

    model_config = SettingsConfigDict(
        env_prefix="MARKET_GATEWAY_",
        case_sensitive=False,
        extra="ignore",
    )

    api_key: SecretStr = SecretStr("")
    nbe_base_url: str = ""
    nbe_exchange_path: str = "/NBEeChannelManager/CallMW.aspx"
    gold_base_url: str = ""
    gold_quote_path: str = "/price/XAU"
    fund_base_url: str = ""
    fund_quote_path: str = "/markets/EGX/stocks/EGX30ETF"
    timeout_seconds: float = Field(default=10.0, gt=0, le=30)

    @field_validator("nbe_base_url", "gold_base_url", "fund_base_url")
    @classmethod
    def _validate_optional_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("source base URLs must be absolute http(s) URLs")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("source base URLs must not contain credentials, query, or fragment")
        return value

    @field_validator(
        "nbe_exchange_path",
        "gold_quote_path",
        "fund_quote_path",
    )
    @classmethod
    def _validate_path(cls, value: str) -> str:
        if not value.startswith("/") or "://" in value:
            raise ValueError("source paths must be relative paths beginning with /")
        return value

    @property
    def configured(self) -> bool:
        return bool(self.nbe_base_url and self.gold_base_url and self.fund_base_url)

    def require_configured(self) -> None:
        if not self.configured:
            raise RuntimeError(
                "MARKET_GATEWAY_NBE_BASE_URL, MARKET_GATEWAY_GOLD_BASE_URL, and "
                "MARKET_GATEWAY_FUND_BASE_URL must all be configured"
            )
