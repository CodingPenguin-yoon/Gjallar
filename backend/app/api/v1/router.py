"""Composition router for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.guided_qm import router as guided_qm_router
from app.api.v1.insights import router as insights_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.jobs_compat import router as jobs_compat_router
from app.api.v1.operations import router as operations_router
from app.api.v1.vm_actions import router as vm_actions_router
from app.api.v1.vm_create_compat import router as vm_create_compat_router
from app.auth.dependencies import require_viewer

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_viewer)])
router.include_router(inventory_router)
router.include_router(operations_router)
router.include_router(guided_qm_router)
router.include_router(insights_router)
router.include_router(jobs_compat_router)
router.include_router(vm_actions_router)
router.include_router(vm_create_compat_router)
