import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.deps import get_current_claims, get_tenant_session
from app.models.finance import Invoice, InvoiceStatus
from app.models.payments import PaymentIntent, PaymentIntentStatus
from app.payments import get_gateway
from app.payments.camerpay import verify_webhook_signature
from app.reconciliation import reconcile_intent
from app.schemas import PaymentCallbackRequest, PaymentIntentCreateRequest, PaymentIntentResponse

router = APIRouter()
logger = logging.getLogger("finance.payments")


def _ensure_owns_invoice(invoice: Invoice, claims: dict) -> None:
    if claims.get("role") == "student" and invoice.student_id != uuid.UUID(claims["sub"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")


@router.post(
    "/invoices/{invoice_id}/payment-intents",
    response_model=PaymentIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_intent(
    invoice_id: uuid.UUID,
    payload: PaymentIntentCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> PaymentIntent:
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    _ensure_owns_invoice(invoice, claims)
    if invoice.status != InvoiceStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice is not pending payment")

    intent = PaymentIntent(
        institution_id=invoice.institution_id,
        invoice_id=invoice.id,
        amount_xaf=invoice.amount_xaf,
        provider=settings.camerpay_provider,
        provider_reference=str(uuid.uuid4()),
        payer_msisdn=payload.payer_msisdn,
    )
    session.add(intent)
    # Persisted BEFORE the provider call - a crash/timeout below still
    # leaves a real row the worker's poller can reconcile against later.
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A payment is already in progress for this invoice"
        ) from exc

    try:
        result = await get_gateway().request_to_pay(
            reference=intent.provider_reference, amount_xaf=intent.amount_xaf, payer_msisdn=intent.payer_msisdn
        )
        if result.redirect_url or result.provider_transaction_id:
            intent.redirect_url = result.redirect_url
            intent.provider_transaction_id = result.provider_transaction_id
            await session.commit()
    except Exception:
        # The intent row already exists and stays PENDING; the worker's
        # poll loop (and this invoice's next status check) will keep
        # trying rather than losing the payment attempt.
        logger.exception(
            "CamerPay request_to_pay call failed for intent %s; left pending for reconciliation", intent.id
        )

    return intent


@router.get("/payment-intents/{intent_id}", response_model=PaymentIntentResponse)
async def get_payment_intent(
    intent_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> PaymentIntent:
    intent = await session.get(PaymentIntent, intent_id)
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment intent not found")
    invoice = await session.get(Invoice, intent.invoice_id)
    if invoice is not None:
        _ensure_owns_invoice(invoice, claims)

    if intent.status == PaymentIntentStatus.PENDING:
        # Give the caller a fresher status than waiting for the next
        # worker poll tick, using the exact same reconciliation path.
        # reconcile_intent mutates this same identity-mapped instance and
        # commits with expire_on_commit=False, so no refresh is needed -
        # and refreshing here would re-SELECT in a new transaction after
        # the tenant RLS context set by SET LOCAL has already ended.
        await reconcile_intent(session, get_gateway(), intent.id)

    return intent


@router.post("/payments/callback", status_code=status.HTTP_200_OK)
async def payment_callback(payload: PaymentCallbackRequest) -> dict:
    """Public MTN callback endpoint - carries no ERP session, and its body
    is NEVER trusted as settlement authority (see phase5-plan.md): only
    the reference is used, to look up the matching intent and re-check its
    real status via the gateway itself.
    """
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(PaymentIntent).where(PaymentIntent.provider_reference == payload.reference)
        )
        intent = result.scalar_one_or_none()
        if intent is None:
            return {"status": "ignored"}
        new_status = await reconcile_intent(session, get_gateway(), intent.id)
    return {"status": new_status.value if new_status else "ignored"}


@router.post("/payments/callback/camerpay", status_code=status.HTTP_200_OK)
async def camerpay_webhook(request: Request) -> dict:
    """Public camerpay.biz webhook endpoint - form-encoded (NOT json) and
    HMAC-SHA256 signed, see https://camerpay.biz/docs/webhooks. Same rule
    as the generic /payments/callback above: even after signature
    verification, the body's status is only used to pick which intent to
    re-check via an authenticated GET .../status call, never posted
    directly (see reconcile_intent) - a valid signature proves the sender
    knows our secret, not that the status hasn't changed again since.
    """
    form = await request.form()
    txn_uuid = str(form.get("uuid", ""))
    invoice_id = str(form.get("invoice_id", ""))
    webhook_status = str(form.get("status", ""))
    amount = str(form.get("amount", ""))
    signature = request.headers.get("X-CamerPay-Signature") or str(form.get("signature", ""))

    if not verify_webhook_signature(
        txn_uuid=txn_uuid, invoice_id=invoice_id, status=webhook_status, amount=amount, signature=signature
    ):
        logger.warning("Rejected camerpay webhook with invalid signature for invoice_id=%s", invoice_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(PaymentIntent).where(PaymentIntent.provider_reference == invoice_id))
        intent = result.scalar_one_or_none()
        if intent is None:
            return {"status": "ignored"}
        if intent.provider_transaction_id is None and txn_uuid:
            # Back-fill from the now-signature-verified webhook body, in
            # case the process that called request_to_pay crashed after
            # camerpay accepted the request but before persisting its
            # transaction_uuid itself. Committing here ends the current
            # transaction, so the SET LOCAL platform context from above
            # goes with it (see app/core/tenant_context.py) - it must be
            # re-applied before reconcile_intent's own query below, or
            # RLS silently returns zero rows in the new transaction.
            intent.provider_transaction_id = txn_uuid
            await session.commit()
            await set_platform_context(session)
        new_status = await reconcile_intent(session, get_gateway(), intent.id)
    return {"status": new_status.value if new_status else "ignored"}
