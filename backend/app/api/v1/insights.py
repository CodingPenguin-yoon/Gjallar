"""Observe-only Insights HTTP routes for ``/api/v1``."""

from fastapi import APIRouter

from app.api.v1.responses import success_response
from app.insights.facade import get_insights

router = APIRouter()


@router.get("/insights")
def get_insights_route() -> dict:
    """Return availability-aware, observe-only operational Insights."""
    return success_response(get_insights(), meta={"mode": "observe_only"})
