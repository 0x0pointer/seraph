import stripe
from app.core.config import settings

stripe.api_key = settings.stripe_secret_key


def _price_map() -> dict[str, str]:
    return {
        "starter": settings.stripe_price_starter,
        "pro": settings.stripe_price_pro,
    }


def get_or_create_customer(email: str, name: str, existing_id: str | None) -> str:
    if existing_id:
        return existing_id
    customer = stripe.Customer.create(email=email, name=name or email)
    return customer.id


def create_checkout_session(customer_id: str, plan: str, success_url: str, cancel_url: str) -> str:
    price_id = _price_map()[plan]
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        metadata={"plan": plan},
    )
    return session.url


def create_portal_session(customer_id: str, return_url: str) -> str:
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str):
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
