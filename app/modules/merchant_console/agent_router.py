# backend/app/modules/merchant_console/agent_router.py
"""
Agent router — supports the Merchant Dashboard's AgentPanel.

Endpoints:
  POST /agent/merchant/{merchant_id}/chat
  POST /agent/merchant/{merchant_id}/actions/{action_id}/confirm
  POST /agent/merchant/{merchant_id}/actions/{action_id}/dismiss

The agent runs all proposed actions through the same service-layer /
permissions paths as the manual endpoints above and audit-logs them.
This initial stub returns a simple canned reply so the UI is wired up;
a real LLM agent can be plugged in later without changing the contract.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user, to_uuid
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.user import User, UserRole
from app.schemas.merchant_console import (
    ActionStatus,
    AgentChatResponse,
    AgentConfirmResponse,
    ProposedAction,
)

router = APIRouter()

get_current_active_user_depends = Depends(get_current_active_user)
get_db_depends = Depends(get_db)


async def _verify_merchant_access(
    merchant_id: str,
    current_user: User,
    db: AsyncSession,
) -> Merchant:
    """Verify the current user can act on behalf of this merchant."""
    merchant = await db.get(Merchant, to_uuid(merchant_id))
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Merchant not found",
        )
    if current_user.role == UserRole.PLATFORM_ADMIN:
        return merchant
    if merchant.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this merchant's agent",
        )
    return merchant


@router.post(
    "/agent/merchant/{merchant_id}/chat",
    response_model=AgentChatResponse,
)
async def agent_chat(
    merchant_id: str,
    payload: dict,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Chat with the store assistant.

    Returns a reply and an optional list of *proposed* actions that the
    merchant must confirm before they execute.
    """
    await _verify_merchant_access(merchant_id, current_user, db)

    message = payload.get("message", "")
    section = payload.get("context", {}).get("section", "overview")

    # ── Stub response ──────────────────────────────────────────────────
    reply = (
        f"I'm looking at your {section.replace('_', ' ')} section. "
        f"You asked: “{message}”. "
        "I can help you manage orders, products, payouts, and more. "
        "What would you like me to do next?"
    )

    return AgentChatResponse(reply=reply, proposed_actions=[])


@router.post(
    "/agent/merchant/{merchant_id}/actions/{action_id}/confirm",
    response_model=AgentConfirmResponse,
)
async def agent_confirm_action(
    merchant_id: str,
    action_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Confirm and execute a proposed agent action.

    In the stub implementation, actions are not persisted — the endpoint
    simply acknowledges the confirmation so the UI progresses.
    """
    await _verify_merchant_access(merchant_id, current_user, db)

    # In a full implementation this would look up the proposed action,
    # execute it through the appropriate service, and return the result.
    # For now, acknowledge.
    return AgentConfirmResponse(
        ok=True,
        result_summary=f"Action {action_id} confirmed and acknowledged.",
    )


@router.post(
    "/agent/merchant/{merchant_id}/actions/{action_id}/dismiss",
    response_model=AgentConfirmResponse,
)
async def agent_dismiss_action(
    merchant_id: str,
    action_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Dismiss a proposed agent action without executing it."""
    await _verify_merchant_access(merchant_id, current_user, db)

    return AgentConfirmResponse(
        ok=True,
        result_summary=f"Action {action_id} dismissed.",
    )


def get_router():
    return router
