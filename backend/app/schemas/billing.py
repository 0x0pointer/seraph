from datetime import datetime
from pydantic import BaseModel, Field


# ── Payment Methods ───────────────────────────────────────────────────────────

class AddPaymentMethodRequest(BaseModel):
    cardholder_name: str = Field(..., min_length=1, max_length=100)
    card_brand: str = Field(..., pattern="^(visa|mastercard|amex|discover|card)$")
    card_last4: str = Field(..., min_length=4, max_length=4, pattern="^[0-9]{4}$")
    card_exp_month: int = Field(..., ge=1, le=12)
    card_exp_year: int = Field(..., ge=2024, le=2099)


class PaymentMethodRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    cardholder_name: str
    card_brand: str
    card_last4: str
    card_exp_month: int
    card_exp_year: int
    is_default: bool
    created_at: datetime


# ── Invoices ──────────────────────────────────────────────────────────────────

class InvoiceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    invoice_number: str
    amount: float
    currency: str
    status: str
    description: str | None
    period_start: datetime
    period_end: datetime
    paid_at: datetime | None
    created_at: datetime


class CreateInvoiceRequest(BaseModel):
    """Admin-only: manually create an invoice for a user."""
    user_id: int
    amount: float = Field(..., gt=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    description: str | None = None
    period_start: datetime
    period_end: datetime
    status: str = Field("open", pattern="^(open|paid|failed|void)$")


class UpdateInvoiceRequest(BaseModel):
    """Admin-only: change invoice status."""
    status: str = Field(..., pattern="^(open|paid|failed|void)$")
