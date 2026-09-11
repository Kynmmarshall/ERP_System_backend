import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.deps import get_current_claims, get_tenant_session
from app.models.finance import Invoice, InvoiceStatus
from app.models.payments import PaymentIntent, PaymentIntentStatus
from app.payments import get_gateway
from app.reconciliation import reconcile_intent, reconcile_intent_as_platform_admin
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
        provider="mtn_momo",
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
        await get_gateway().request_to_pay(
            reference=intent.provider_reference, amount_xaf=intent.amount_xaf, payer_msisdn=intent.payer_msisdn
        )
    except Exception:
        # The intent row already exists and stays PENDING; the worker's
        # poll loop (and this invoice's next status check) will keep
        # trying rather than losing the payment attempt.
        logger.exception("CamerPay request_to_pay call failed for intent %s; left pending for reconciliation", intent.id)

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
        await reconcile_intent(session, get_gateway(), intent.id)
        await session.refresh(intent)

    return intent


@router.post("/payments/callback", status_code=status.HTTP_200_OK)
async def payment_callback(payload: PaymentCallbackRequest) -> dict:
    """Public MTN callback endpoint - carries no ERP session, and its body
    is NEVER trusted as settlement authority (see phase5-plan.md): only
    the reference is used, to look up the matching intent and re-check its
    real status via the gateway itself.
    """
    result_query = select(PaymentIntent).where(PaymentIntent.provider_reference == payload.reference)
    async with SessionFactory() as session:
        result = await session.execute(result_query)
        intent = result.scalar_one_or_none()
        if intent is None:
            return {"status": "ignored"}
        new_status = await reconcile_intent_as_platform_admin(session, get_gateway(), intent.id)
    return {"status": new_status.value if new_status else "ignored"}
