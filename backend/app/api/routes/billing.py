from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.api.routes.auth import get_current_user
from app.models.billing import Invoice, PaymentMethod
from app.models.user import User
from app.schemas.billing import (
    AddPaymentMethodRequest,
    CreateInvoiceRequest,
    InvoiceRead,
    PaymentMethodRead,
    UpdateInvoiceRequest,
)

router = APIRouter(prefix="/billing", tags=["billing"])


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


# ── Payment Methods ───────────────────────────────────────────────────────────


@router.get("/payment-methods", response_model=list[PaymentMethodRead])
async def list_payment_methods(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(PaymentMethod)
        .where(PaymentMethod.user_id == current_user.id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.asc())
    )
    return result.scalars().all()


@router.post("/payment-methods", response_model=PaymentMethodRead, status_code=201)
async def add_payment_method(
    data: AddPaymentMethodRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Check if user already has 5 payment methods
    result = await session.execute(
        select(PaymentMethod).where(PaymentMethod.user_id == current_user.id)
    )
    existing = result.scalars().all()
    if len(existing) >= 5:
        raise HTTPException(status_code=400, detail="Maximum of 5 payment methods allowed")

    is_default = len(existing) == 0  # first card is automatically the default

    method = PaymentMethod(
        user_id=current_user.id,
        cardholder_name=data.cardholder_name,
        card_brand=data.card_brand,
        card_last4=data.card_last4,
        card_exp_month=data.card_exp_month,
        card_exp_year=data.card_exp_year,
        is_default=is_default,
    )
    session.add(method)
    await session.commit()
    await session.refresh(method)
    return method


@router.patch("/payment-methods/{method_id}/default", response_model=PaymentMethodRead)
async def set_default_payment_method(
    method_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    method = await session.get(PaymentMethod, method_id)
    if not method or method.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Payment method not found")

    # Clear existing default
    result = await session.execute(
        select(PaymentMethod).where(
            PaymentMethod.user_id == current_user.id,
            PaymentMethod.is_default.is_(True),
        )
    )
    for m in result.scalars().all():
        m.is_default = False

    method.is_default = True
    await session.commit()
    await session.refresh(method)
    return method


@router.delete("/payment-methods/{method_id}", status_code=204)
async def delete_payment_method(
    method_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    method = await session.get(PaymentMethod, method_id)
    if not method or method.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Payment method not found")

    was_default = method.is_default
    await session.delete(method)
    await session.flush()

    # If we deleted the default, promote the oldest remaining card
    if was_default:
        result = await session.execute(
            select(PaymentMethod)
            .where(PaymentMethod.user_id == current_user.id)
            .order_by(PaymentMethod.created_at.asc())
            .limit(1)
        )
        next_method = result.scalars().first()
        if next_method:
            next_method.is_default = True

    await session.commit()


# ── Invoices ──────────────────────────────────────────────────────────────────


@router.get("/invoices", response_model=list[InvoiceRead])
async def list_invoices(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Invoice)
        .where(Invoice.user_id == current_user.id)
        .order_by(Invoice.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


# ── Admin: Invoice management ─────────────────────────────────────────────────


@router.post("/admin/invoices", response_model=InvoiceRead, status_code=201)
async def admin_create_invoice(
    data: CreateInvoiceRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)

    # Generate invoice number: INV-YYYYMMDD-<user_id>-<count+1>
    result = await session.execute(
        select(Invoice).where(Invoice.user_id == data.user_id)
    )
    count = len(result.scalars().all())
    invoice_number = f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{data.user_id}-{count + 1:03d}"

    paid_at = datetime.now(timezone.utc) if data.status == "paid" else None
    invoice = Invoice(
        user_id=data.user_id,
        invoice_number=invoice_number,
        amount=data.amount,
        currency=data.currency.upper(),
        status=data.status,
        description=data.description,
        period_start=data.period_start,
        period_end=data.period_end,
        paid_at=paid_at,
    )
    session.add(invoice)
    await session.commit()
    await session.refresh(invoice)
    return invoice


@router.patch("/admin/invoices/{invoice_id}", response_model=InvoiceRead)
async def admin_update_invoice(
    invoice_id: int,
    data: UpdateInvoiceRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)

    invoice = await session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = data.status
    if data.status == "paid" and not invoice.paid_at:
        invoice.paid_at = datetime.now(timezone.utc)
    elif data.status != "paid":
        invoice.paid_at = None

    await session.commit()
    await session.refresh(invoice)
    return invoice
