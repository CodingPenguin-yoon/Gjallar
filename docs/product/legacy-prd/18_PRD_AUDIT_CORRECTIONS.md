# Gjallar PRD Audit Corrections

Updated: 2026-05-08 18:38 KST

> Historical audit note:
> This document records an older create-first PRD cleanup. Current MVP product source of truth is `drs-advisor/`; if this document conflicts with that folder, `drs-advisor/` wins.

## 0. 목적

사용자 지시에 따라 PRD를 Gjallar 중심으로 다시 정리한 내역이다.

## 1. 발견한 문제

기존 PRD에는 아래 문제가 있었다.

- 외부 앱 운영 도구와의 경계 문서가 너무 커서 Gjallar가 부속품처럼 보일 수 있었다.
- “배포 대상” 표현이 많아 Gjallar의 중심이 VM/Proxmox가 아니라 앱 배포처럼 보일 수 있었다.
- 예시 프로젝트명과 앱 운영 개념이 PRD 안에 섞여 있었다.
- 기존 code inventory가 오래된 구현 방향을 source of truth처럼 보이게 할 위험이 있었다.

## 2. 정정한 내용

### 2.1 외부 경계 축소

`02_HEIMDALL_BOUNDARY.md`를 제거하고 `02_EXTERNAL_BOUNDARIES.md`로 대체했다.
외부 시스템은 read-only readiness/risk consumer로만 다룬다.

### 2.2 Gjallar 중심 재정의

Master PRD에서 Gjallar 소유 영역을 Proxmox/VM 계층으로 고정했다.
앱 build/deploy/log/DB migration은 Gjallar 비소유 영역으로 명시했다.

### 2.3 Deployment Target 표현 정리

“Heimdall 배포 대상” 중심 표현을 `Runtime Target`으로 바꿨다.
Runtime Target은 Gjallar가 준비 완료로 표시한 VM 후보일 뿐, 제품 중심이 아니다.

### 2.4 예시 프로젝트명 제거

특정 앱/프로젝트 예시는 제거했다.
PRD에는 Gjallar 제품 결정에 필요한 일반 개념만 남겼다.

### 2.5 기존 코드 문서 재정의

`10_CODE_INVENTORY.md`는 상세 inventory가 아니라 fresh inventory 정책 문서로 바꿨다.
기존 코드는 PRD를 흔드는 기준이 아니라, 구현 전 검증할 재료다.

### 2.6 잘못 전달된 외부 참고 자료 제거

사용자가 잘못 첨부한 자료는 Gjallar 자료가 아니므로 PRD에서 제거했다.
PRD는 해당 자료를 IPAM, evidence source, manifest source of truth로 사용하지 않는다.

### 2.7 활성 문서 정리

2026-05-08 당시 정리 결정은 루트에는 `README.md`만 남기고 활성 제품 source of truth를 당시 `PRD/`로 단일화하는 것이었다.
현재 활성 제품 source of truth는 `docs/product/drs-advisor/`다.
정리 전 백업:

```text
/home/yoon/.hermes/cache/gjallar_docs_before_prd_only_20260508_181832.tar.gz
```

## 3. 남은 검토 포인트

- MVP 실제 생성 profile은 `general-vm` 하나로 결정됨
- 실제 Proxmox node/storage/bridge/template 이름 확정
- IaC repo/state 위치 확정
- MVP 생성 테스트에 쓸 안전 IP range 확정
