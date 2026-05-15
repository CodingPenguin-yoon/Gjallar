# 한국어 제품 문서

이 폴더는 한국어 독자를 위한 제품 방향 설명입니다. 기준 우선순위는 active code/tests, [영어 product index](../../product/README.md), [DRS Advisor product docs](../../product/drs-advisor/README.md), [current state](../../current/README.md)입니다.

제품 문서는 "왜 이 도메인이 존재하는가"와 target direction을 설명합니다. Current 구현 여부는 항상 [current](../current/README.md)와 [architecture](../architecture/README.md)에서 확인합니다.

## 문서

- [DRS Advisor](drs-advisor/README.md)

## 제품 framing

Gjallar는 Proxmox Operations & Risk Console입니다. DRS Advisor가 next MVP success line이고 Create VM은 supporting capability입니다. Proxmox actual state가 VM/node/task/storage/network truth이며, Gjallar는 intent, policy, approvals, fingerprints, jobs, artifacts, audit, reconciliation state를 저장하는 방향입니다.
