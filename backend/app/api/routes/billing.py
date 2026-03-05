from datetime import datetime, timezone

import stripe as stripe_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.api.routes.auth import get_current_user
from app.models.billing import Invoice, PaymentMethod
from app.models.organization import Organization
from app.models.user import User
from app.schemas.billing import (
    AddPaymentMethodRequest,
    CreateInvoiceRequest,
    InvoiceRead,
    PaymentMethodRead,
    UpdateInvoiceRequest,
    _default_period_start,
    _default_period_end,
)
from app.services import stripe_service

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

    # Validate user exists
    target_user = (await session.execute(select(User).where(User.id == data.user_id))).scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    period_start = data.period_start or _default_period_start()
    period_end = data.period_end or _default_period_end()

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
        period_start=period_start,
        period_end=period_end,
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


# ── Stripe ────────────────────────────────────────────────────────────────────


class CheckoutRequest(BaseModel):
    plan: str           # "starter" | "pro"
    entity: str = "user"   # "user" | "org"


@router.post("/checkout")
async def create_checkout(
    data: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if data.plan not in ("starter", "pro"):
        raise HTTPException(400, "Invalid plan — must be 'starter' or 'pro'")
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe is not configured on this server")

    if data.entity == "org" and current_user.org_id:
        org = (await session.execute(
            select(Organization).where(Organization.id == current_user.org_id)
        )).scalar_one_or_none()
        if not org:
            raise HTTPException(404, "Organization not found")
        customer_id = stripe_service.get_or_create_customer(
            current_user.email or "", org.name, org.stripe_customer_id
        )
        org.stripe_customer_id = customer_id
        session.add(org)
    else:
        customer_id = stripe_service.get_or_create_customer(
            current_user.email or "", current_user.full_name or current_user.username,
            current_user.stripe_customer_id
        )
        current_user.stripe_customer_id = customer_id
        session.add(current_user)

    await session.commit()

    base = settings.frontend_url
    url = stripe_service.create_checkout_session(
        customer_id, data.plan,
        success_url=f"{base}/dashboard/billing",
        cancel_url=f"{base}/dashboard/billing",
    )
    return {"url": url}


@router.get("/portal")
async def billing_portal(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe is not configured on this server")

    customer_id = current_user.stripe_customer_id
    if not customer_id and current_user.org_id:
        org = (await session.execute(
            select(Organization).where(Organization.id == current_user.org_id)
        )).scalar_one_or_none()
        customer_id = org.stripe_customer_id if org else None
    if not customer_id:
        raise HTTPException(400, "No active Stripe subscription found")

    url = stripe_service.create_portal_session(
        customer_id, f"{settings.frontend_url}/dashboard/billing"
    )
    return {"url": url}


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe_service.construct_webhook_event(payload, sig)
    except Exception:
        raise HTTPException(400, "Invalid webhook signature")

    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        customer_id = data["customer"]
        sub_id = data["subscription"]
        plan = data.get("metadata", {}).get("plan", "pro")
        user = (await session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if user:
            user.plan = plan
            user.stripe_subscription_id = sub_id
            user.subscription_status = "active"
            session.add(user)
        else:
            org = (await session.execute(
                select(Organization).where(Organization.stripe_customer_id == customer_id)
            )).scalar_one_or_none()
            if org:
                org.plan = plan
                org.stripe_subscription_id = sub_id
                org.subscription_status = "active"
                session.add(org)

    elif etype == "invoice.paid":
        await _upsert_stripe_invoice(session, data, "paid")

    elif etype == "invoice.payment_failed":
        await _upsert_stripe_invoice(session, data, "failed")
        await _set_subscription_status(session, data["customer"], "past_due")

    elif etype == "customer.subscription.deleted":
        await _set_subscription_status(session, data["customer"], "canceled")
        await _downgrade_to_free(session, data["customer"])

    elif etype == "customer.subscription.updated":
        status = data.get("status", "active")
        await _set_subscription_status(session, data["customer"], status)

    await session.commit()
    return {"ok": True}


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe is not configured on this server")

    sub_id = current_user.stripe_subscription_id
    if not sub_id and current_user.org_id:
        org = (await session.execute(
            select(Organization).where(Organization.id == current_user.org_id)
        )).scalar_one_or_none()
        sub_id = org.stripe_subscription_id if org else None
    if not sub_id:
        raise HTTPException(400, "No active subscription found")

    stripe_lib.Subscription.modify(sub_id, cancel_at_period_end=True)
    return {"detail": "Subscription will cancel at end of billing period"}


# ── Stripe webhook helpers ────────────────────────────────────────────────────

async def _upsert_stripe_invoice(session, data: dict, status: str) -> None:
    """Create or update a local invoice record from a Stripe invoice event."""
    stripe_inv_id = data.get("id")
    if not stripe_inv_id:
        return

    customer_id = data.get("customer")
    sub_id = data.get("subscription")
    amount_paid = (data.get("amount_paid") or data.get("amount_due") or 0) / 100.0
    hosted_url = data.get("hosted_invoice_url")
    period_start_ts = data.get("period_start")
    period_end_ts = data.get("period_end")

    from datetime import datetime, timezone as tz
    period_start = datetime.fromtimestamp(period_start_ts, tz=tz.utc) if period_start_ts else _default_period_start()
    period_end = datetime.fromtimestamp(period_end_ts, tz=tz.utc) if period_end_ts else _default_period_end()

    # Look up the user or org owning this customer_id
    user = (await session.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )).scalar_one_or_none()
    user_id = user.id if user else None

    if not user_id:
        # Org-level customer — find any user in that org
        org = (await session.execute(
            select(Organization).where(Organization.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if org:
            owner = (await session.execute(
                select(User).where(User.id == org.owner_id)
            )).scalar_one_or_none()
            user_id = owner.id if owner else None

    if not user_id:
        return

    # Check if invoice already exists
    existing = (await session.execute(
        select(Invoice).where(Invoice.stripe_invoice_id == stripe_inv_id)
    )).scalar_one_or_none()

    if existing:
        existing.status = status
        if status == "paid" and not existing.paid_at:
            existing.paid_at = datetime.now(tz.utc)
        existing.hosted_invoice_url = hosted_url
        session.add(existing)
    else:
        count = (await session.execute(
            select(Invoice).where(Invoice.user_id == user_id)
        )).scalars().all()
        inv_num = f"INV-{datetime.now(tz.utc).strftime('%Y%m%d')}-{user_id}-{len(count) + 1:03d}"
        invoice = Invoice(
            user_id=user_id,
            invoice_number=inv_num,
            amount=amount_paid,
            currency="USD",
            status=status,
            description="Subscription payment",
            period_start=period_start,
            period_end=period_end,
            paid_at=datetime.now(tz.utc) if status == "paid" else None,
            stripe_invoice_id=stripe_inv_id,
            stripe_subscription_id=sub_id,
            hosted_invoice_url=hosted_url,
        )
        session.add(invoice)


async def _set_subscription_status(session, customer_id: str, status: str) -> None:
    user = (await session.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )).scalar_one_or_none()
    if user:
        user.subscription_status = status
        session.add(user)
        return

    org = (await session.execute(
        select(Organization).where(Organization.stripe_customer_id == customer_id)
    )).scalar_one_or_none()
    if org:
        org.subscription_status = status
        session.add(org)


async def _downgrade_to_free(session, customer_id: str) -> None:
    user = (await session.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )).scalar_one_or_none()
    if user:
        user.plan = "free"
        user.stripe_subscription_id = None
        user.subscription_status = "inactive"
        session.add(user)
        return

    org = (await session.execute(
        select(Organization).where(Organization.stripe_customer_id == customer_id)
    )).scalar_one_or_none()
    if org:
        org.plan = "free"
        org.stripe_subscription_id = None
        org.subscription_status = "inactive"
        session.add(org)
