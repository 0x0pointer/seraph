from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardrail import GuardrailConfig
from app.schemas.guardrail import GuardrailCreate, GuardrailUpdate


async def list_guardrails(session: AsyncSession) -> list[GuardrailConfig]:
    result = await session.execute(select(GuardrailConfig).order_by(GuardrailConfig.order))
    return list(result.scalars().all())


async def get_guardrail(session: AsyncSession, guardrail_id: int) -> GuardrailConfig | None:
    return await session.get(GuardrailConfig, guardrail_id)


async def create_guardrail(session: AsyncSession, data: GuardrailCreate) -> GuardrailConfig:
    guardrail = GuardrailConfig(**data.model_dump())
    session.add(guardrail)
    await session.commit()
    await session.refresh(guardrail)
    return guardrail


async def update_guardrail(
    session: AsyncSession, guardrail_id: int, data: GuardrailUpdate
) -> GuardrailConfig | None:
    guardrail = await session.get(GuardrailConfig, guardrail_id)
    if not guardrail:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(guardrail, key, value)
    await session.commit()
    await session.refresh(guardrail)
    return guardrail


async def toggle_guardrail(session: AsyncSession, guardrail_id: int) -> GuardrailConfig | None:
    guardrail = await session.get(GuardrailConfig, guardrail_id)
    if not guardrail:
        return None
    guardrail.is_active = not guardrail.is_active
    await session.commit()
    await session.refresh(guardrail)
    return guardrail


async def delete_guardrail(session: AsyncSession, guardrail_id: int) -> bool:
    guardrail = await session.get(GuardrailConfig, guardrail_id)
    if not guardrail:
        return False
    await session.delete(guardrail)
    await session.commit()
    return True
