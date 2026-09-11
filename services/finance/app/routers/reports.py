import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_claims, get_tenant_session
from app.models.finance import Invoice
from app.models.ledger import Receipt

router = APIRouter()


@router.get("/invoices/{invoice_id}/receipt")
async def invoice_receipt(
    invoice_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Response:
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    if claims.get("role") == "student" and invoice.student_id != uuid.UUID(claims["sub"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    result = await session.execute(select(Receipt).where(Receipt.invoice_id == invoice_id))
    receipt = result.scalar_one_or_none()
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No receipt yet for this invoice")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER)
    styles = getSampleStyleSheet()
    table = Table(
        [
            ["Receipt ID", str(receipt.id)],
            ["Invoice ID", str(receipt.invoice_id)],
            ["Amount (XAF)", f"{receipt.amount_xaf:,}"],
            ["Issued at", receipt.issued_at.isoformat()],
        ],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
            ]
        )
    )
    doc.build([Paragraph("ICT University - Payment Receipt", styles["Title"]), Spacer(1, 12), table])
    return Response(content=buffer.getvalue(), media_type="application/pdf")
