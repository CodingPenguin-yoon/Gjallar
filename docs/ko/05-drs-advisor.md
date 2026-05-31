# DRS Advisor 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [DRS Advisor product direction](../product/drs-advisor/README.md), [Placement and target DRS Advisor](../architecture/placement-drs-advisor/overview.md), [target DRS API](../architecture/api/target-drs-api.md), [target DRS flow](../architecture/flows/drs-approve-migrate-reconcile.md).

DRS Advisor는 Gjallar의 다음 MVP product target입니다. 현재 frontend `/drs`는 recommendation/check 화면에 더해 manual VM policy configuration과 local approval packet/job intent creation을 제공합니다. Backend에는 identity/policy evidence, operation locks, local approval/job substrate, narrow operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview가 있습니다.

자세한 한국어 제품 설명은 [product/drs-advisor/README.md](product/drs-advisor/README.md)를 봅니다.

## 현재 상태

- `/drs` route는 `DRS Advisor` label을 사용합니다.
- `frontend/src/utils/drsAdvisor.js`가 backend DRS endpoint를 소비합니다.
- 현재 recommendation은 CPU/Memory current usage, imbalance, bridge/storage/passthrough/target pressure evidence, red risk exclusion을 사용합니다.
- Execution은 `available: false`, `read_only: true`, `executable: false`, `allowed_actions: []`입니다.
- 현재 `/api/v1/drs/summary`, `/recommendations`, detail, `/check`는 recommendation/check output이며 `executable=false`, `allowed_actions=[]`를 유지합니다.
- `GET/PUT /api/v1/drs/policies*`와 `/drs` policy review UI로 manual VM migration policy를 설정할 수 있습니다.
- `/api/v1/drs/recommendations/{recommendation_id}/approval-packets`는 local approval/job/artifact만 쓰고 migration을 시작하지 않습니다.
- `/api/v1/drs/migration-jobs/{job_id}/execute`는 stored approval/job, fresh gates, live Proxmox evidence, operation locks 이후에만 실행되는 narrow operator-only backend route입니다.
- `/api/v1/drs/migration-jobs/{job_id}/reconcile-preview`는 read-only preview입니다.
- `/drs`에는 live migration execute UI와 corrective reconcile UI가 없습니다.

## 목표

DRS Advisor는 Proxmox-native migration advisor and control tower입니다. 남은 gap은 broad live execution UI, corrective reconcile UI, richer policy rule/full metadata editor, corrective mutation, background automation, automatic DRS, live DRS smoke, recommendation-level migrate aliases입니다.

금지 표현은 VMware DRS replacement, VMware DRS compatible, automatic DRS for Proxmox, backup product입니다.

## 핵심 안전 원칙

- Check Now는 참고용입니다. 실행 허가로 재사용하지 않습니다.
- Final pre-check는 Approve & Migrate 직전에 매번 새로 수행해야 합니다.
- VMID는 identity가 아니라 locator입니다.
- same VMID + different fingerprint는 Identity Mismatch이며 모든 작업을 차단해야 합니다.
- Create VM native runner는 DRS migration executor가 아닙니다.
