# DECISIONS

Last updated: 2026-05-09 00:50 KST

## Locked decisions

1. Gjallar는 Proxmox를 VMware처럼 쓰게 해주는 VM/인프라 운영 콘솔이다.
2. 이번 구현은 legacy 보존 리팩터링이 아니라 PRD 기준 clean-room core + selective salvage 재작성이다.
3. 구현 순서는 PRD → contract/schema RED tests → 최소 GREEN 구현 → fresh review다.
4. 첫 MVP 생성 profile은 `general-vm` 하나다.
5. red risk는 승인으로도 우회 불가, yellow risk는 명시 ack 필요다.
6. secret 원문은 Git/DB/artifact/log/UI/API/docs에 저장하지 않는다.
7. autonomous cron은 Set-runner worker 10m + read-only heartbeat 5m 운영을 기본으로 한다.
8. 이 Discord thread/session은 Gjallar만 관리한다.
9. commit/push/delete/Terraform apply/Proxmox write/power-on은 사용자 명시 승인 전 금지다.
10. Set 0~7은 비파괴/TDD 범위에서 자율 진행 가능하지만 Set 8+ live side effect는 hard stop이다.

## Review notes from 2026-05-09 00:42 KST

- PRD/22의 Set 설계는 큰 방향이 맞다.
- 보강한 gate: Set 8+ 승인, Set 12 deletion 금지, GitOps denylist 확대, Jobs/Risks/approve/execute tests, pre-apply live recheck.

## Operational decisions from Set 0

- 2026-05-09 00:50 KST: Codex VM에는 `/mnt/hermes_data/프로젝트/Gjallar/PRD`가 마운트되어 있지 않으므로, 이번 rewrite run의 Codex VM PRD 접근 방식은 baseline artifact 내부 snapshot copy로 한다. 위치: `artifacts/rewrite-baseline/20260509-004801-KST/prd-snapshot/PRD/`. 장기 worker가 live PRD sync를 필요로 하면 별도 read-only mount를 검증한 뒤 전환한다.
