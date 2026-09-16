# 정리 전 문서 원본

평소 기준 문서는 [문서 안내](../README.md)의 핵심 문서다. 이곳은 과거 결정·상세 계약·검증 원문이 필요할 때만 사용한다.

## 보존 범위

[2026-09-16 정리 전 원본](2026-09-16-documents-before-consolidation.tar.gz)은 Markdown 63개와 `MANIFEST.json`을 포함한다. 원본 파일별 SHA-256·크기와 Git HEAD의 동일 blob 존재 여부를 기록했다. 11개는 당시 HEAD에 같은 내용이 있고, 나머지 52개는 이동 링크 수정·미커밋 문서 등을 포함하므로 Git만으로 현재 원문을 복원할 수 없어 함께 보존했다.

- 당시 Git HEAD: `60b8a34622ab8885ed9dca20bd13df0da2dee1c0`
- 압축 파일 SHA-256: `d84c46839ab36ca6dca52b9efca438f7622e326069dbb28194c727c7d9baac3d`
- 포함: 이전 제품 명세, ADR, 종료 계획, 도메인·API·DB·실행 흐름, live evidence 원문 6개, 통합 전 현재 문서.
- 제외: `.env`, 자격 증명 파일, 로컬 Obsidian 설정. `local-workspace/`의 기존 설정은 별도로 남아 있고 Git 제외다.
- 원본은 당시 상태이며 새 실행 권한이 아니다. 압축 파일을 현재 문서와 함께 계속 갱신하지 않는다. 새 기록은 work에 작성한다.

## 확인과 복원

저장소 루트에서 목록 확인:

```bash
tar -tzf project-docs/archive/2026-09-16-documents-before-consolidation.tar.gz
```

현재 파일을 덮어쓰지 않도록 새 임시 디렉터리에 복원:

```bash
gjallar_docs_restore=$(mktemp -d)
tar -xzf project-docs/archive/2026-09-16-documents-before-consolidation.tar.gz -C "$gjallar_docs_restore"
```

복원본에는 당시 상대 링크도 보존돼 있다. `MANIFEST.json`의 SHA-256과 복원한 파일을 비교할 수 있다. 과거 기록을 수정하거나 live 명령을 재실행하기 위한 절차는 아니다.
