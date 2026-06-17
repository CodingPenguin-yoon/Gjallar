# Gjallar DRS Advisor MVP PRD

This file is a numeric PRD index.
The current source of truth is the split document set under [`docs/product/drs-advisor/`](../../product/drs-advisor/README.md).

Read in this order:

1. [`docs/product/drs-advisor/01_PRODUCT_DIRECTION.md`](../../product/drs-advisor/01_PRODUCT_DIRECTION.md)
2. [`docs/product/drs-advisor/02_UI_AND_FLOWS.md`](../../product/drs-advisor/02_UI_AND_FLOWS.md)
3. [`docs/product/drs-advisor/03_DATA_DB_AND_IDENTITY.md`](../../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md)
4. [`docs/product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md`](../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md)
5. [`docs/product/drs-advisor/05_IMPLEMENTATION_PLAN.md`](../../product/drs-advisor/05_IMPLEMENTATION_PLAN.md)

Summary:

- Gjallar is a Proxmox enterprise operations platform, not a backup product.
- Current MVP direction is DRS Advisor.
- Gjallar should not claim to replace VMware DRS.
- DRS Advisor observes Proxmox-native inventory/migration/HA/storage/task state, recommends CPU/Memory-based migrations, gates execution by identity/metadata/policy/final pre-check, runs manual approved live migration through Proxmox, tracks UPID/jobs/artifacts, and supports reconciliation.
- Create VM Terraform/GitOps remains a secondary existing capability.
