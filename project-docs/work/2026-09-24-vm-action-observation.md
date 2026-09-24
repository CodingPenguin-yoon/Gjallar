# VM 작업의 전체 partial 차단 제거

- 상태: IMPLEMENTED
- 근거: 2026-09-24 사용자 요청 “파셜 없애자”.

## 문제와 범위

VM 상세를 정상 조회해도 다른 자원의 관찰 누락이 연결을 degraded/partial로 만들어 시작·종료·삭제 도구 전체를 숨겼다. 연결 성공과 개별 조회 결과를 분리한다. snapshot을 얻으면 연결은 live/fresh이며 항목별 availability·failed_targets는 유지한다. 시작·종료는 새 snapshot에서 해당 VM의 config/detail 조회 실패만 차단하고 기존 대상·상태·권한·잠금·결과 확인을 유지한다. 삭제 등은 기존 작업별 서버 검사를 그대로 사용한다. 생성·Guided 등 별도 작업의 필수 정보 검증은 제거하지 않는다.

## 검증·복구·비범위

다른 VM·guest agent·storage 조회 누락에도 전원 작업 검토가 가능하고 대상 config/detail 누락·연결 실패는 차단되는 회귀 검사를 추가한다. 공통 로컬/컨테이너 검증과 diff 검사를 실행한다. DB·권한·잠금·재시도·복구 계약은 바꾸지 않는다. 실제 VM mutation, 배포·서버 재시작은 수행하지 않는다. 문제 발생 시 이 코드 변경만 되돌릴 수 있으며 데이터 migration은 없다.

## 결과

- 서버 연결의 전체 partial/degraded 판정을 제거했다. 조회 결과의 항목별 complete/failed_targets는 유지한다.
- 전원 API는 thread pool에서 새 snapshot을 얻고 대상 config/detail을 확인한다. 다른 대상 누락은 무관하며 대상 필수 정보 누락은 구체적인 오류와 함께 차단한다.
- 웹의 전체 작업 숨김을 해제하고 대상 정보 누락 문구를 구체화했다. 삭제는 기존 정지·자원 검토·대상 확인·권한 조건을 그대로 적용한다.
- 아키텍처·개발 안내·로드맵을 갱신했다.
- `pnpm run verify`: 성공. client 267개, backend 1,692개 통과·78개 건너뜀, frontend tests/Lint/build 성공. 로컬 Node 26의 engines 경고와 기존 bundle 크기 경고가 있다.
- 마지막 전원 조회 thread pool 변경은 전원 API 계약 검사 73개로 추가 검증했다. 대상별 관찰·inventory 계약 검사 17개도 통과했다.
- `pnpm run verify:container`: 성공. client test image·backend 1,692개 통과/78개 건너뜀·Node 24 frontend tests/Lint/build·production image 빌드를 확인했다. 서비스는 기동하지 않았다. 초기 sandbox Docker 소켓 접근 실패 후 허용된 권한으로 재실행했다.
- 문서 계약 검사 10개와 `git diff --check`도 통과했다.
- 실제 VM mutation·배포·서버 재시작은 수행하지 않았다. 운영 서버 반영과 실제 실행 검증이 남아 있다.
