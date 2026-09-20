"""Composition router for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.maintenance import router as maintenance_router
from app.api.v1.host_storage import router as host_storage_router
from app.api.v1.host_network import router as host_network_router

from app.api.v1.vm_backup import router as vm_backup_router
from app.api.v1.vm_restore import router as vm_restore_router
from app.api.v1.vm_migrate import router as vm_migrate_router
from app.api.v1.guided_qm import router as guided_qm_router
from app.api.v1.insights import router as insights_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.jobs_compat import router as jobs_compat_router
from app.api.v1.operations import router as operations_router
from app.api.v1.template_test import router as template_test_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.vm_actions import router as vm_actions_router
from app.api.v1.vm_network import router as vm_network_router
from app.api.v1.vm_clone import router as vm_clone_router
from app.api.v1.vm_console import router as vm_console_router
from app.api.v1.vm_image_build import router as vm_image_build_router
from app.api.v1.vm_image_cleanup import router as vm_image_cleanup_router
from app.api.v1.vm_template import router as vm_template_router
from app.api.v1.vm_delete import router as vm_delete_router
from app.api.v1.vm_compute import router as vm_compute_router
from app.api.v1.vm_disk import router as vm_disk_router
from app.api.v1.vm_create_compat import router as vm_create_compat_router
from app.api.v1.proxmox_setup import router as proxmox_setup_router
from app.auth.dependencies import require_viewer

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_viewer)])
router.include_router(inventory_router)
router.include_router(operations_router)
router.include_router(template_test_router)
router.include_router(monitoring_router)
router.include_router(guided_qm_router)
router.include_router(insights_router)
router.include_router(jobs_compat_router)
router.include_router(vm_actions_router)
router.include_router(vm_compute_router)
router.include_router(vm_delete_router)
router.include_router(vm_template_router)
router.include_router(vm_image_build_router)
router.include_router(vm_image_cleanup_router)
router.include_router(vm_console_router)
router.include_router(vm_clone_router)
router.include_router(vm_network_router)
router.include_router(vm_disk_router)
router.include_router(vm_create_compat_router)
router.include_router(proxmox_setup_router)

router.include_router(vm_backup_router)
router.include_router(vm_restore_router)
router.include_router(vm_migrate_router)

router.include_router(maintenance_router)
router.include_router(host_storage_router)
router.include_router(host_network_router)
