# 기능 흐름: 기능명

- 상태: `DRAFT` <!-- DRAFT | APPROVED -->
- 최종 검토일: `<YYYY-MM-DD>`
- 관련 요구사항·도메인: `<링크>`

## 목적과 진입점

- 해결하는 업무 문제:
- 시작 조건:
- 호출 주체:
- 최종 결과:

## 성공 흐름

```text
Entry
→ Application flow
→ Domain rule
→ Persistence 또는 External adapter
→ Result
```

각 단계의 입력, 책임, 반환값, 다음 단계 전달값을 설명한다.

## 데이터 변환

```text
External input
→ Boundary model
→ Application input
→ Domain value
→ Persistence·external parameters
→ Result
```

의미 있는 변환과 그 이유만 기록한다.

## 상태와 트랜잭션

- 변경되는 상태:
- 데이터 소유자:
- 트랜잭션 경계:
- 정합성 규칙:

## 실패 흐름

| 실패 지점 | 오류 변환 | 상태 변화 | 재시도·보상 | 사용자 결과 |
|---|---|---|---|---|
|  |  |  |  |  |

## 멱등성과 동시성

- 중복 요청 처리:
- 동시 상태 변경:
- timeout·취소:

## 구현 위치

| 단계 | 파일·심볼 | 책임 |
|---|---|---|
|  |  |  |

## 검증

- 정상 흐름:
- 경계·실패 흐름:
- 통합·계약 테스트:
