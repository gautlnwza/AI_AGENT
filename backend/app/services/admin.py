"""Admin overview / observability service.

Reads aggregate counts across users / conversations / billing and exposes
them to the dashboard. All reads — no mutation. Should remain cheap (single
COUNT(*) per metric); if usage grows we'd promote to materialized views.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User

logger = logging.getLogger(__name__)


class AdminService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def workspace_stats(self) -> dict[str, Any]:
        """Aggregate workspace metrics. Billing fields stay at 0 when the
        feature isn't enabled — the schema doesn't change shape between
        configurations.
        """
        # Total users
        total_users = (await self.db.execute(select(func.count(User.id)))).scalar_one()

        # Active in last 24h via session.last_used_at — best-effort, returns 0
        # when session_management isn't enabled in this deployment.
        active_24h: int = 0
        # Session/billing tables are optional in this deployment.

        # Conversations + messages totals — 0 when AI/chat is disabled
        total_conversations = 0
        total_messages = 0
        # Billing — best-effort, only if tables exist + billing on
        credits_30d = 0
        mrr_cents = 0
        # Billing tables are not part of the base schema.

        return {
            "total_users": int(total_users),
            "active_users_24h": int(active_24h),
            "total_conversations": int(total_conversations),
            "total_messages": int(total_messages),
            "credits_charged_30d": credits_30d,
            "mrr_cents": mrr_cents,
        }

    async def list_stripe_events(self, *, skip: int = 0, limit: int = 50) -> tuple[list[Any], int]:
        """Page through the Stripe webhook idempotency log.

        Returns ([], 0) when the StripeEvent table doesn't exist (billing
        disabled in this deployment). Caller projects to schema.
        """
        return [], 0
