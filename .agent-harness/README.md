# AI Project Harness

이 디렉터리는 프로젝트에 설치된 공통 하네스 본체다. 프로젝트별 내용을 직접 추가하거나 수정하지 않는다.

## 관리 영역

```text
AGENTS.md
.agent-harness/
.agents/skills/
```

공통 하네스를 갱신할 때는 같은 버전의 세 영역을 함께 교체하고 `manifest.toml`의 버전을 확인한다. 교체 후에는 실제 `project-docs/project-profile.md`의 하네스 버전만 새 버전으로 동기화한다. 프로젝트가 선택한 preset, 기술 스택, 명령, 아키텍처는 Project Profile이 계속 소유하며 공통 파일로 덮어쓰지 않는다.

## 구성

- `core/`: 기술 중립적인 설계·구현·문서·검증 원칙
- `presets/`: 선택한 기술에 대한 설계 질문과 구현 지침
- `templates/`: `project-docs/` 생성에 사용하는 양식
- `.agents/skills/`: 신규 설계, 계획, 문서 동기화, 리뷰, 기존 프로젝트 도입, 아키텍처 개선 절차

## 프로젝트별 영역

- 공동 명세: `project-docs/`
- 개인 학습·조사: `.agent-local/`
- 실제 코드와 루트 `README.md`, `.gitignore`: 프로젝트 소유

## 원칙

- 공통 하네스는 특정 아키텍처, 데이터베이스, ORM, 패키지 관리자를 자동 선택하지 않는다.
- 최신 기술 버전은 프로젝트 설계 시 공식 지원 정보를 확인한 뒤 사용자와 결정한다.
- 고위험 작업만 공유 Plan과 독립 리뷰를 요구한다.
- 커스텀 검사기, CI/CD, Runbook, `.codex/` 설정은 기본 범위에 포함하지 않는다.
