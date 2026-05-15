# DRS Advisor 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [DRS Advisor product direction](../product/drs-advisor/README.md), [Placement and target DRS Advisor](../architecture/placement-drs-advisor/overview.md), [target DRS API](../architecture/api/target-drs-api.md), [target DRS flow](../architecture/flows/drs-approve-migrate-reconcile.md).

DRS Advisor는 Gjallar의 다음 MVP product target입니다. 현재 구현은 아직 backend DRS Advisor가 아니라 read-only Placement seed입니다.

자세한 한국어 제품 설명은 [product/drs-advisor/README.md](product/drs-advisor/README.md)를 봅니다.

## 현재 상태

- `/placement` route는 존재하지만 label/책임은 아직 Placement 중심입니다.
- `frontend/src/utils/placement.js`가 inventory/jobs/risks를 조합해 후보를 계산합니다.
- 현재 recommendation은 CPU/Memory current usage, imbalance, bridge/storage evidence, red risk exclusion을 사용합니다.
- Execution은 `available: false`, `readOnly: true`, `allowedActions: []`입니다.
- 현재 `/api/v1/drs/*` route는 없습니다.

## 목표

DRS Advisor는 Proxmox-native migration advisor and control tower입니다. 목표는 backend-owned recommendation, identity/fingerprint/policy 기반 이동 가능성 판단, final pre-check, operation lock, approval-gated live migration, UPID tracking, post-check, reconciliation입니다.

금지 표현은 VMware DRS replacement, VMware DRS compatible, automatic DRS for Proxmox, backup product입니다.

## 핵심 안전 원칙

- Check Now는 참고용입니다. 실행 허가로 재사용하지 않습니다.
- Final pre-check는 Approve & Migrate 직전에 매번 새로 수행해야 합니다.
- VMID는 identity가 아니라 locator입니다.
- same VMID + different fingerprint는 Identity Mismatch이며 모든 작업을 차단해야 합니다.
- Create VM native runner는 DRS migration executor가 아닙니다.
