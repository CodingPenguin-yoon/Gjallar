# Gjallar Review Checklist

## 0. 목적

구현/리뷰 시 PRD 위반을 빠르게 찾기 위한 체크리스트다.

## 1. 제품 경계

- [ ] Gjallar가 Proxmox/VM 계층에 집중한다.
- [ ] 앱 deploy/log/DB migration 기능이 들어오지 않았다.
- [ ] 외부 시스템 연계가 read-only readiness/risk 중심이다.
- [ ] Runtime Target이 Gjallar core보다 앞서지 않는다.

## 2. Safety

- [ ] red risk는 실행 불가다.
- [ ] yellow risk는 Review & Confirm이 있다.
- [ ] dangerous action에 approval이 있다.
- [ ] power on/shutdown/reboot는 첫 구현 MVP에 노출되지 않고, power-action slice에서 일반 Confirm을 요구한다.
- [ ] hard stop/reset이 MVP에 노출되지 않는다.
- [ ] plan diff가 사용자에게 보인다.
- [ ] IP/VMID/storage/template/preflight가 빠지지 않았다.

## 3. Secret

- [ ] Proxmox token이 DB/artifact/log에 남지 않는다.
- [ ] SSH private key가 저장/출력되지 않는다.
- [ ] env secret이 UI/API 응답에 노출되지 않는다.

## 4. Manifest/IaC

- [ ] Gjallar write allowlist를 지킨다.
- [ ] Terraform/Ansible engine code를 자동 수정하지 않는다.
- [ ] Terraform state를 Git에 넣지 않는다.
- [ ] job workspace가 per-job으로 분리된다.

## 5. UX

- [ ] Profile 선택이 먼저다.
- [ ] 고급 hardware override는 접혀 있다.
- [ ] Nodes/VMs/Detail 흐름이 한 화면에서 자연스럽다.
- [ ] Risks / Alerts가 핵심 화면으로 보인다.

## 6. Tests

- [ ] contract tests가 먼저 있다.
- [ ] 구현 후 fresh review를 별도 컨텍스트에서 한다.
- [ ] 테스트가 구현 버그를 억지로 통과시키지 않는다.
