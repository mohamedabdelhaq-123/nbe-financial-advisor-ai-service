import os
import subprocess
import sys

import httpx
import pytest

from app.market_data_gateway.config import MarketGatewaySettings
from app.market_data_gateway.main import create_app


def test_gateway_import_does_not_require_the_full_ai_service_environment():
    """The standalone production gateway must not instantiate app.main settings."""

    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("AI_SERVICE_")
    }
    result = subprocess.run(
        [sys.executable, "-c", "from app.market_data_gateway.main import app"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _settings(api_key: str = "gateway-secret") -> MarketGatewaySettings:
    return MarketGatewaySettings(
        api_key=api_key,
        nbe_base_url="https://nbe.test",
        gold_base_url="https://gold.test",
        fund_base_url="https://fund.test",
    )


@pytest.mark.asyncio
async def test_health_does_not_require_a_gateway_credential():
    transport = httpx.ASGITransport(app=create_app(_settings()))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "configured": "true"}


@pytest.mark.asyncio
async def test_health_stays_up_without_sources_for_disabled_deployments():
    transport = httpx.ASGITransport(app=create_app(MarketGatewaySettings()))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "configured": "false"}


@pytest.mark.asyncio
async def test_quote_endpoint_rejects_missing_or_wrong_gateway_credential():
    transport = httpx.ASGITransport(app=create_app(_settings()))
    request_body = {
        "instruments": [
            {
                "instrument_id": "a15230a2-6029-4a9e-88fc-205ebffb6bad",
                "code": "usd-egp-customer-buy",
                "provider_symbol": "USD_EGP_BUY",
                "asset_class": "currency",
            }
        ]
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        missing = await client.post("/v1/quotes", json=request_body)
        wrong = await client.post(
            "/v1/quotes",
            json=request_body,
            headers={"Authorization": "Bearer wrong-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
