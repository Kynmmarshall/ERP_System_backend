"""Unit tests for the real camerpay.biz aggregator adapter, mocking the
HTTP layer with httpx.MockTransport (no extra test dependency needed) -
verifies request shape/headers and response parsing against the
documented contract, without making real network calls.
"""
import json
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.payments.camerpay import CamerPayGateway


def _install_mock_transport(monkeypatch, handler) -> None:
    import app.payments.camerpay as camerpay_module

    # Capture the REAL AsyncClient before patching - `httpx` is one shared
    # module object, so patching camerpay_module.httpx.AsyncClient also
    # affects any call made from inside this factory itself; using the
    # patched name in here would recurse into `factory` again.
    real_async_client = camerpay_module.httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(camerpay_module.httpx, "AsyncClient", factory)


async def test_request_to_pay_sends_documented_payload_and_parses_response(monkeypatch) -> None:
    monkeypatch.setattr(settings, "camerpay_token", "test-token")
    monkeypatch.setattr(settings, "camerpay_base_url", "https://camerpay.biz/api")
    monkeypatch.setattr(settings, "camerpay_merchant_callback_url", "https://example.com/api/v1/finance/payments/callback/camerpay")
    monkeypatch.setattr(settings, "camerpay_merchant_return_url", "https://example.com/finance")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/payment/initiate"
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert body["amount"] == 5000
        assert body["currency"] == "XAF"
        assert body["customer_phone"] == "+237690000000"
        assert body["merchant_invoice_id"] == "ref-123"
        assert body["merchant_callback_url"] == "https://example.com/api/v1/finance/payments/callback/camerpay"
        assert body["merchant_return_url"] == "https://example.com/finance"
        return httpx.Response(
            200,
            json={
                "success": True,
                "transaction_uuid": "5add2319-f71b-4f2d-a4f4-97fe0d11c1d4",
                "status": "pending",
                "pay_url": "https://camerpay.biz/pay/5add2319-f71b-4f2d-a4f4-97fe0d11c1d4",
                "redirect_url": "https://camerpay.biz/pay/5add2319-f71b-4f2d-a4f4-97fe0d11c1d4",
            },
        )

    _install_mock_transport(monkeypatch, handler)

    gateway = CamerPayGateway()
    result = await gateway.request_to_pay(reference="ref-123", amount_xaf=5000, payer_msisdn="+237690000000")

    assert result.redirect_url == "https://camerpay.biz/pay/5add2319-f71b-4f2d-a4f4-97fe0d11c1d4"
    assert result.provider_transaction_id == "5add2319-f71b-4f2d-a4f4-97fe0d11c1d4"


async def test_get_status_maps_completed_to_successful(monkeypatch) -> None:
    monkeypatch.setattr(settings, "camerpay_token", "test-token")
    monkeypatch.setattr(settings, "camerpay_base_url", "https://camerpay.biz/api")
    txn_id = "5add2319-f71b-4f2d-a4f4-97fe0d11c1d4"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/payment/{txn_id}/status"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "success": True,
                "transaction": {"uuid": txn_id, "status": "completed", "amount": 5000, "currency": "XAF"},
            },
        )

    _install_mock_transport(monkeypatch, handler)

    gateway = CamerPayGateway()
    result = await gateway.get_status(
        reference="ref-123",
        requested_at=datetime.now(UTC),
        payer_msisdn="+237690000000",
        provider_transaction_id=txn_id,
    )

    assert result == "SUCCESSFUL"


async def test_get_status_maps_pending_and_processing_and_failed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "camerpay_token", "test-token")
    monkeypatch.setattr(settings, "camerpay_base_url", "https://camerpay.biz/api")
    txn_id = "5add2319-f71b-4f2d-a4f4-97fe0d11c1d4"
    provider_status = {"value": "pending"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": True, "transaction": {"uuid": txn_id, "status": provider_status["value"]}},
        )

    _install_mock_transport(monkeypatch, handler)
    gateway = CamerPayGateway()

    for value, expected in [("pending", "PENDING"), ("processing", "PENDING"), ("failed", "FAILED")]:
        provider_status["value"] = value
        result = await gateway.get_status(
            reference="ref-123",
            requested_at=datetime.now(UTC),
            payer_msisdn="+237690000000",
            provider_transaction_id=txn_id,
        )
        assert result == expected


async def test_get_status_without_transaction_id_is_pending_without_an_http_call(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not make an HTTP call without a provider_transaction_id")

    _install_mock_transport(monkeypatch, handler)

    gateway = CamerPayGateway()
    result = await gateway.get_status(
        reference="ref-123", requested_at=datetime.now(UTC), payer_msisdn="+237690000000", provider_transaction_id=None
    )

    assert result == "PENDING"
