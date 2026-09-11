import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerDirection, LedgerEntry, LedgerEntryType


@dataclass(frozen=True)
class LedgerLine:
    entry_type: LedgerEntryType
    direction: LedgerDirection
    amount_xaf: int
    reference_type: str
    reference_id: uuid.UUID


async def post_balanced(
    session: AsyncSession, *, institution_id: uuid.UUID, lines: list[LedgerLine], description: str
) -> uuid.UUID:
    """Writes every line of one posting under a shared posting_id, after
    asserting debits == credits - a real double-entry balance check, not
    just a convention. Raises ValueError (caller's transaction rolls back)
    rather than silently posting an unbalanced entry.
    """
    debit_total = sum(line.amount_xaf for line in lines if line.direction == LedgerDirection.DEBIT)
    credit_total = sum(line.amount_xaf for line in lines if line.direction == LedgerDirection.CREDIT)
    if debit_total != credit_total:
        raise ValueError(f"Unbalanced ledger posting: debits={debit_total} credits={credit_total}")

    posting_id = uuid.uuid4()
    for line in lines:
        session.add(
            LedgerEntry(
                institution_id=institution_id,
                posting_id=posting_id,
                entry_type=line.entry_type,
                direction=line.direction,
                amount_xaf=line.amount_xaf,
                reference_type=line.reference_type,
                reference_id=line.reference_id,
                description=description,
            )
        )
    return posting_id
