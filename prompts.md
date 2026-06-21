# 제안서 자동 검토 시스템 — Claude Code 단계별 프롬프트

각 단계를 순서대로 실행하세요. 이전 단계 완료 후 다음 단계를 시작하세요.

---

## STEP 1. 프로젝트 셋업 + 인증

```
컨설팅 제안서를 자동으로 검토하는 내부 웹 애플리케이션을 만든다.
이 단계에서는 프로젝트 기본 구조를 잡고, 회원가입·로그인 기능을 완성한다.

## 기술 스택 (고정 — 이후 단계에서도 동일하게 사용)
- Backend: FastAPI (Python 3.12)
- Frontend: Next.js 15 (App Router, TypeScript, Tailwind CSS)
- Database: PostgreSQL
- ORM: SQLAlchemy (async) + Alembic (마이그레이션)
- Auth: JWT (python-jose) + bcrypt (패스워드 해싱)
- 패키지 관리: backend는 uv, frontend는 npm
- 폴더 구조: 모노레포 (루트에 backend/, frontend/ 분리)

## 디렉토리 구조
proposal-review/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py        # DB 연결 (async SQLAlchemy)
│   │   ├── models/
│   │   │   └── user.py
│   │   ├── schemas/
│   │   │   └── user.py
│   │   ├── routers/
│   │   │   └── auth.py
│   │   └── core/
│   │       ├── config.py      # 환경변수 (pydantic-settings)
│   │       └── security.py    # JWT 생성/검증, bcrypt
│   ├── alembic/
│   ├── pyproject.toml
│   └── .env.example
└── frontend/
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx            # 로그인 페이지로 리다이렉트
    │   ├── (auth)/
    │   │   ├── login/page.tsx
    │   │   └── register/page.tsx
    │   └── (dashboard)/
    │       └── layout.tsx      # 인증 가드 (토큰 없으면 /login으로)
    ├── lib/
    │   └── api.ts              # axios 인스턴스, 토큰 자동 첨부
    └── ...

## DB 스키마 — users 테이블
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

## API 엔드포인트
POST /api/auth/register
  Body: { "username": "string", "password": "string" }
  - 아이디 중복 시 409
  - 패스워드 규칙 위반 시 422 (영문+숫자 포함 6자 이상)
  - 성공 시 201 + { "id", "username" }

POST /api/auth/login
  Body: { "username": "string", "password": "string" }
  - 실패 시 401
  - 성공 시 200 + { "access_token", "token_type": "bearer" }
  - JWT 만료: 24시간

GET /api/auth/me   (Authorization: Bearer <token> 필요)
  - 현재 로그인 사용자 정보 반환

## 패스워드 규칙 (백엔드·프론트엔드 모두 검증)
- 6자 이상
- 영문 1자 이상 포함
- 숫자 1자 이상 포함

## 프론트엔드 화면
- /login: 아이디 + 패스워드 입력, 로그인 버튼, 회원가입 링크
- /register: 아이디 + 패스워드 + 패스워드 확인 입력, 회원가입 버튼
- 로그인 성공 시 /dashboard로 이동 (dashboard는 "준비 중" 텍스트만 표시)
- JWT를 localStorage에 저장, 이후 모든 API 요청 헤더에 자동 첨부
- (dashboard) 레이아웃: 토큰 없거나 만료 시 /login으로 리다이렉트

## 환경변수 (.env.example)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/proposal_review
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256

## 완료 기준
- 회원가입 → 로그인 → /dashboard 진입 흐름이 브라우저에서 동작
- 중복 아이디 가입 시 에러 메시지 표시
- 패스워드 규칙 위반 시 에러 메시지 표시
- 로그인하지 않은 상태에서 /dashboard 접근 시 /login으로 리다이렉트
```

---

## STEP 2. 파일 업로드 + 검토 건 관리

```
STEP 1에서 FastAPI + Next.js 인증 시스템을 구축했다.
이 단계에서는 제안서 파일 업로드와 검토 건(ReviewJob) 관리 기능을 만든다.

## DB 스키마 추가

-- 검토 건
CREATE TABLE review_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
      -- draft(업로드 중) | pending(검토 대기) | processing(검토 중)
      -- | completed(완료) | failed(오류)
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- 업로드된 파일
CREATE TABLE review_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES review_jobs(id) ON DELETE CASCADE,
    proposal_type VARCHAR(20) NOT NULL,
      -- qualitative(정성제안서) | quantitative(정량제안서) | presentation(발표본)
    original_filename VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,  -- UUID 기반 경로, 외부 노출 금지
    file_size_bytes BIGINT NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    uploaded_at TIMESTAMP DEFAULT NOW()
);

## 파일 저장 규칙
- 저장 경로: backend/uploads/{job_id}/{file_id}/{original_filename}
- 외부에서 직접 접근 불가 (FastAPI에서 스트리밍으로만 제공)
- 파일명은 원본 보존, 경로는 UUID로 예측 불가하게 구성

## API 엔드포인트 (모두 JWT 인증 필요)

POST /api/jobs
  - 빈 검토 건 생성 (status: draft)
  - 응답: { "job_id": "uuid" }

POST /api/jobs/{job_id}/files
  - multipart/form-data
  - 필드: file (파일), proposal_type (qualitative|quantitative|presentation)
  - 허용 확장자: .ppt .pptx .doc .docx .pdf
  - 파일 크기 제한: 50MB
  - 제한 위반 시 400 에러
  - 본인 job이 아닌 경우 403
  - status가 draft가 아닌 경우 409 (이미 검토 시작됨)
  - 응답: { "file_id", "original_filename", "proposal_type" }

DELETE /api/jobs/{job_id}/files/{file_id}
  - status가 draft일 때만 허용
  - 파일을 DB와 스토리지에서 모두 삭제

GET /api/jobs/{job_id}
  - 검토 건 상세 (파일 목록 포함)
  - 응답:
    {
      "id", "status", "created_at",
      "files": [
        {
          "id", "proposal_type", "original_filename",
          "file_size_bytes", "uploaded_at"
        }
      ],
      "file_counts": {
        "qualitative": 2,
        "quantitative": 1,
        "presentation": 0
      }
    }

GET /api/jobs
  - 본인의 검토 건 목록 (최신순)
  - 응답: 위 구조의 배열 (files 필드 포함)

## 프론트엔드 화면

### /dashboard (검토 건 목록)
- 상단: "새 검토 요청" 버튼 → 클릭 시 새 job 생성 후 /jobs/{id}/upload로 이동
- 검토 건 목록 카드 형태로 표시
  - 생성일시, 상태 배지(draft/대기/처리중/완료/오류)
  - 파일 수 요약: "정성 2개 · 정량 1개 · 발표본 없음"
  - 클릭 시 해당 검토 건으로 이동

### /jobs/{id}/upload (파일 업로드)
- 3개 섹션: 정성제안서 / 정량제안서 / 발표본
- 각 섹션:
  - 파일 선택 버튼 (드래그 앤 드롭 지원)
  - 업로드된 파일 목록 (파일명, 크기, 삭제 버튼)
  - 정성·정량은 다중 파일 허용, 발표본은 1개만
- 허용 형식 안내: .ppt .pptx .doc .docx .pdf
- 파일 크기 초과 시 즉시 에러 메시지
- "검토 시작" 버튼: 파일이 1개 이상일 때만 활성화
  - 클릭 시 확인 모달: "업로드 후에는 파일 변경이 불가합니다. 검토를 시작할까요?"
  - 확인 → POST /api/jobs/{id}/start 호출 → /jobs/{id}/status로 이동

POST /api/jobs/{job_id}/start
  - status를 draft → pending으로 변경
  - 파일이 없으면 400

## 완료 기준
- 파일 업로드 → 파일 목록 표시 → 삭제 흐름이 동작
- 허용 확장자 외 파일 업로드 시 에러 메시지
- 50MB 초과 파일 업로드 시 에러 메시지
- "검토 시작" 클릭 후 status가 pending으로 변경됨을 확인
- 다른 사용자의 job에 파일 업로드 시 403 반환
```

---

## STEP 3. 파일 파싱 파이프라인

```
STEP 2에서 파일 업로드와 검토 건 관리가 완성되었다.
이 단계에서는 업로드된 파일에서 텍스트와 위치 정보(페이지/슬라이드 번호)를 추출하는
파싱 파이프라인을 만든다. 이 모듈은 STEP 4의 LLM 엔진이 호출해서 사용한다.

## 사용 라이브러리 (고정)
- PPTX: python-pptx
- DOCX: python-docx
- PDF: pdfplumber
  - 텍스트 레이어 없는 스캔 PDF는 추출 불가 → 별도 처리

## 파싱 결과 데이터 구조

각 파일 파싱 결과는 아래 구조의 리스트로 반환:
{
  "file_id": "uuid",
  "original_filename": "파일명.pptx",
  "proposal_type": "qualitative",
  "pages": [
    {
      "page_number": 1,       # 1-based
      "text": "슬라이드 1의 텍스트 전체"
    },
    {
      "page_number": 2,
      "text": "슬라이드 2의 텍스트 전체"
    }
  ],
  "total_pages": 10,
  "parse_error": null         # 파싱 실패 시 에러 메시지 문자열
}

## 파싱 규칙

### PPTX (python-pptx)
- 각 슬라이드를 page로 취급 (page_number = 슬라이드 번호, 1-based)
- 슬라이드 내 모든 Shape에서 텍스트 추출
  - shape.has_text_frame인 것만 처리
  - 각 paragraph의 text를 줄바꿈으로 합쳐서 하나의 텍스트로
- 마스터 슬라이드/레이아웃 텍스트는 제외 (내용 슬라이드만)
- 텍스트가 없는 슬라이드는 pages 배열에 포함하되 text를 빈 문자열로

### DOCX (python-docx)
- 단락(paragraph) 단위로 수집
- "페이지" 개념이 없으므로 단락 50개를 1 page로 묶음
  - page_number는 1, 2, 3... 으로 증가
  - 마지막 페이지는 50개 미만일 수 있음
- 표(table) 내 텍스트도 추출 (cell.text 사용)

### PDF (pdfplumber)
- 각 PDF 페이지를 page로 취급
- page.extract_text() 사용
- extract_text() 결과가 None이거나 빈 문자열인 페이지가 전체의 80% 이상이면
  "parse_error": "텍스트 레이어를 찾을 수 없습니다. 스캔된 PDF일 수 있습니다."
  로 설정하고 pages는 빈 리스트로 반환

## 파싱 모듈 위치
backend/app/services/parser.py
- parse_file(file_path: str, mime_type: str, file_id: str, original_filename: str, proposal_type: str) -> dict
  - mime_type에 따라 적절한 파서 호출
  - 지원하지 않는 mime_type이면 parse_error에 메시지 설정

## 테스트
backend/tests/test_parser.py 작성:
- 각 포맷별(pptx, docx, pdf) 샘플 파일로 파싱 결과 검증
- page_number가 1부터 시작하는지 확인
- 스캔 PDF에 대한 parse_error 확인
샘플 파일은 테스트 코드 내에서 직접 생성 (python-pptx, python-docx로 테스트용 파일 생성)

## MIME 타입 매핑
.pptx → application/vnd.openxmlformats-officedocument.presentationml.presentation
.ppt  → application/vnd.ms-powerpoint  (파싱 불가 — parse_error: "구버전 PPT 형식은 지원하지 않습니다. PPTX로 변환 후 업로드하세요.")
.docx → application/vnd.openxmlformats-officedocument.wordprocessingml.document
.doc  → application/msword  (파싱 불가 — parse_error: "구버전 DOC 형식은 지원하지 않습니다. DOCX로 변환 후 업로드하세요.")
.pdf  → application/pdf

## 완료 기준
- pytest 실행 시 parser 테스트 통과
- pptx 파싱 시 슬라이드 번호가 정확히 반환됨
- docx 파싱 시 50단락 단위로 페이지가 나뉨
- pdf 파싱 시 페이지 번호가 정확히 반환됨
- 스캔 PDF 처리 시 parse_error 메시지 반환됨
- .ppt/.doc 업로드 시 parse_error 반환됨
```

---

## STEP 4. LLM 검토 엔진

```
STEP 3에서 파일 파싱 파이프라인이 완성되었다.
이 단계에서는 파싱된 텍스트를 LLM에 보내 최상급 표현과 오타를 검출하고,
결과를 DB에 저장하는 비동기 검토 엔진을 만든다.

## 추가 라이브러리
- Celery + Redis (비동기 작업 큐)
- anthropic (Anthropic Python SDK)
- 환경변수에 ANTHROPIC_API_KEY, REDIS_URL 추가

## DB 스키마 추가

CREATE TABLE review_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL REFERENCES review_files(id) ON DELETE CASCADE,
    category VARCHAR(30) NOT NULL,
      -- superlative(최상급 표현) | typo(오타)
    detected_text TEXT NOT NULL,       # 검출된 원문 텍스트
    suggestion TEXT,                   # 오타의 수정 제안 (최상급은 null)
    page_number INTEGER NOT NULL,
    context TEXT,                      # 검출 텍스트 주변 문장 (UI 표시용)
    created_at TIMESTAMP DEFAULT NOW()
);

-- review_files 테이블에 컬럼 추가
ALTER TABLE review_files ADD COLUMN parse_error TEXT;
ALTER TABLE review_files ADD COLUMN total_pages INTEGER;

## Celery 작업 구성
backend/app/workers/
├── celery_app.py    # Celery 인스턴스 설정
└── review_task.py   # 실제 검토 작업

작업 흐름 (review_task.py):
1. ReviewJob 상태를 processing으로 변경, started_at 기록
2. job에 속한 모든 ReviewFile 조회
3. 각 파일별로:
   a. parse_file() 호출하여 텍스트 추출
   b. parse_error 있으면 review_files.parse_error에 저장 후 해당 파일 건너뜀
   c. 페이지별 텍스트를 청크로 묶어 LLM 호출 (아래 청크 전략 참조)
   d. LLM 응답 파싱 후 review_results에 저장
4. 모든 파일 처리 완료 후 ReviewJob 상태를 completed로 변경, completed_at 기록
5. 중간에 예외 발생 시 상태를 failed로 변경, 에러 메시지를 별도 컬럼에 저장
   (review_jobs에 error_message TEXT 컬럼 추가)

## LLM 청크 전략
- 한 번의 LLM 호출에 최대 10페이지 분량의 텍스트
- 각 청크 호출 시 해당 청크에 포함된 page_number 범위를 프롬프트에 명시
- 모델: claude-sonnet-4-6

## LLM 프롬프트 (system + user 구조)

System:
"""
당신은 컨설팅 제안서를 검토하는 전문 편집자입니다.
주어진 텍스트에서 두 가지 항목을 검출해야 합니다.

1. 최상급 표현: 허위사실로 오인될 수 있는 표현
   - 해당 표현: 최초, 최대, 최고, 최선, 최적, 유일, 독보적, 가장, 압도적, 세계 최
   - 해당 표현이 있어도 사실일 수 있으므로 '검토 필요'로만 플래그. 오류로 단정하지 말 것.
   - 고유명사 일부로 포함된 경우(예: 최고급 상품명)는 제외

2. 오타: 한글 또는 영문 맞춤법/철자 오류
   - 전문 용어, 고유명사, 브랜드명, 약어는 오타로 처리하지 말 것
   - 수정 제안은 1개만 제시

출력 형식은 반드시 아래 JSON 형식을 따르세요. JSON 외 다른 텍스트는 출력하지 마세요:
{
  "results": [
    {
      "category": "superlative" | "typo",
      "detected_text": "검출된 텍스트",
      "suggestion": "수정 제안 (오타일 때만, 최상급은 null)",
      "page_number": 페이지번호(정수),
      "context": "검출된 텍스트를 포함한 전후 1~2문장"
    }
  ]
}
결과가 없으면 {"results": []} 반환.
"""

User:
"""
아래는 {filename}의 {start_page}~{end_page} 페이지 내용입니다. 검토해주세요.

[{start_page}페이지]
{page_text}

[{start_page+1}페이지]
{page_text}
...
"""

## API 엔드포인트 추가

POST /api/jobs/{job_id}/start (STEP 2에서 만든 엔드포인트 수정)
  - status를 pending으로 변경
  - Celery 작업을 큐에 등록 (task_id를 review_jobs에 저장)
  - review_jobs에 celery_task_id VARCHAR(255) 컬럼 추가

GET /api/jobs/{job_id}/status
  - { "status", "started_at", "completed_at", "error_message",
      "file_statuses": [{ "file_id", "original_filename", "parse_error" }] }

## 환경변수 추가 (.env.example)
ANTHROPIC_API_KEY=sk-ant-...
REDIS_URL=redis://localhost:6379/0

## 완료 기준
- Redis와 Celery worker가 실행 중인 상태에서 /api/jobs/{id}/start 호출 시
  Celery가 작업을 받아서 처리함
- 처리 완료 후 review_results 테이블에 결과가 저장됨
- 파싱 오류 파일은 건너뛰고 나머지 파일은 정상 처리됨
- 처리 중 예외 발생 시 status가 failed로 변경됨
- GET /api/jobs/{id}/status로 현재 상태 확인 가능
```

---

## STEP 5. 검토 결과 화면

```
STEP 4에서 LLM 검토 엔진이 완성되어 review_results 테이블에 결과가 저장된다.
이 단계에서는 검토 결과를 조회하는 API와 결과 화면을 만든다.

## API 엔드포인트

GET /api/jobs/{job_id}/results
  - 인증 필요, 본인 job만 조회 가능
  - 응답 구조:
    {
      "job_id": "uuid",
      "status": "completed",
      "summary": {
        "total_superlative": 12,
        "total_typo": 5,
        "files_with_issues": 3
      },
      "proposal_types": [
        {
          "type": "qualitative",
          "label": "정성제안서",
          "files": [
            {
              "file_id": "uuid",
              "original_filename": "01_서론.pptx",
              "total_pages": 20,
              "parse_error": null,
              "superlative_count": 4,
              "typo_count": 2,
              "results": [
                {
                  "id": "uuid",
                  "category": "superlative",
                  "detected_text": "세계 최초로",
                  "suggestion": null,
                  "page_number": 3,
                  "context": "당사는 세계 최초로 개발한 솔루션을..."
                },
                {
                  "id": "uuid",
                  "category": "typo",
                  "detected_text": "활용하여",
                  "suggestion": "활용하여 (맞춤법 확인 필요: '활용하여'는 올바른 표현)",
                  "page_number": 7,
                  "context": "이를 활용하여 고객의..."
                }
              ]
            }
          ]
        },
        {
          "type": "quantitative",
          "label": "정량제안서",
          "files": [...]
        },
        {
          "type": "presentation",
          "label": "발표본",
          "files": [...]
        }
      ]
    }
  - 파일이 없는 proposal_type은 proposal_types 배열에서 제외

## 프론트엔드 화면: /jobs/{id}/results

### 레이아웃
- 상단 헤더: "검토 결과" + 검토 건 생성일시 + 상태 배지
- 상단 요약 카드 (3열):
  - 최상급 표현: N건
  - 오타: N건
  - 검토 파일: N개
- 본문: 제안서 종류별 섹션

### 종류별 섹션 (예: 정성제안서)
- 섹션 헤더: "정성제안서" + 파일 수 + 총 검출 건수
- 파일별 카드 (아코디언):
  - 카드 헤더: 파일명 + "최상급 N건 · 오타 N건"
  - 기본 펼쳐진 상태
  - parse_error가 있으면 카드에 경고 배너 표시 ("파싱 오류: {parse_error}")
  - 카드 내부:
    - "최상급 표현" 서브섹션 (노란색 배경 강조)
      - 각 항목: [페이지 N] "context 텍스트" — detected_text를 볼드 처리
      - "검토 필요" 배지
    - "오타" 서브섹션 (빨간색 배경 강조)
      - 각 항목: [페이지 N] "context 텍스트" → 수정 제안: "suggestion"
- 검출 결과가 0건인 파일도 카드로 표시 ("검출된 항목 없음" 메시지)

### 상태별 분기
- status가 pending/processing이면 결과 화면 대신 "검토 진행 중" 화면 표시
  - 스피너 + "검토 중입니다. 파일 크기에 따라 수분이 소요될 수 있습니다."
  - 5초마다 GET /api/jobs/{id}/status 폴링
  - completed 되면 결과 화면으로 자동 전환
- status가 failed면 "검토 중 오류가 발생했습니다" + error_message + "재시도" 버튼
  - "재시도" 클릭 시 POST /api/jobs/{id}/retry 호출
    (review_results 삭제 후 Celery 작업 재등록, status를 pending으로)

### POST /api/jobs/{job_id}/retry
- status가 failed일 때만 허용
- 해당 job의 review_results 전체 삭제
- Celery 작업 재등록, status → pending

## 완료 기준
- /jobs/{id}/results 접근 시 status에 따라 올바른 화면 표시
- 처리 중에는 폴링으로 상태 확인 후 완료 시 결과 자동 표시
- 결과 화면에서 종류별·파일별로 그룹핑된 결과 확인 가능
- 각 검출 항목에 페이지 번호와 context 텍스트 표시
- 최상급 표현과 오타 섹션이 시각적으로 구분됨
- parse_error가 있는 파일에 경고 표시
```

---

## STEP 6. 검토 이력 + 마무리

```
STEP 5에서 검토 결과 화면이 완성되었다.
이 단계에서는 검토 이력 화면을 완성하고, 보안·에러 처리·UX 마무리 작업을 한다.

## 1. 검토 이력 화면 (/dashboard 개선)

STEP 2에서 만든 /dashboard를 아래와 같이 완성한다.

### 화면 구성
- 상단: "새 검토 요청" 버튼 (오른쪽 정렬)
- 검토 건 목록 (최신순, 카드 형태)

### 카드 표시 항목
- 생성일시 (YYYY-MM-DD HH:mm 형식)
- 상태 배지:
  - draft: 회색 "업로드 중"
  - pending: 파란색 "검토 대기"
  - processing: 파란색 + 스피너 "검토 중"
  - completed: 초록색 "완료"
  - failed: 빨간색 "오류"
- 파일 구성 요약: "정성 2개 · 정량 1개 · 발표본 1개" 형태
  (없는 종류는 표시하지 않음)
- 검출 결과 요약 (completed 상태만): "최상급 12건 · 오타 5건"
- 클릭 동작:
  - draft: /jobs/{id}/upload로 이동
  - 그 외: /jobs/{id}/results로 이동

### 빈 상태
- 검토 건이 없으면: "아직 검토 요청이 없습니다. 새 검토 요청을 시작하세요." 안내

### 폴링
- processing 상태인 건이 있으면 10초마다 목록 갱신

## 2. 네비게이션 바 (전체 공통)

모든 (dashboard) 레이아웃 페이지에 공통 적용:
- 왼쪽: 서비스명 "제안서 검토"
- 오른쪽: 로그인된 아이디 표시 + 로그아웃 버튼
- 로그아웃 클릭 시 localStorage 토큰 삭제 + /login으로 이동

## 3. 보안 점검 및 보완

아래 항목을 코드 전체에서 확인하고 누락된 부분 수정:

### API 인가 검증
- 모든 /api/jobs/{job_id}/* 엔드포인트에서 job.user_id == 현재 사용자 확인
- 파일 다운로드/스트리밍 엔드포인트 존재 시 동일하게 적용

### 파일 저장 경로
- storage_path가 uploads/ 디렉토리 밖으로 벗어나는 경로 조작(path traversal) 방지
- 파일 저장 시 반드시 os.path.abspath로 경로 정규화 후 uploads/ 하위인지 검증

### 입력 검증
- username: 영문·숫자·언더스코어만 허용, 4~50자
- proposal_type: 허용 값(qualitative|quantitative|presentation) 외 거부
- 파일 확장자: 서버 사이드에서도 검증 (클라이언트 우회 방지)

### 에러 응답
- 500 에러에서 스택 트레이스나 내부 경로가 클라이언트에 노출되지 않도록 확인
- FastAPI의 exception_handler로 500을 {"detail": "서버 오류가 발생했습니다"} 형태로 반환

## 4. 전체 UX 마무리

### 로딩 상태
- 파일 업로드 중: 업로드 버튼 비활성화 + 진행 상태 표시
- API 호출 중: 버튼 비활성화 + 스피너

### 에러 처리
- API 에러 발생 시 토스트 메시지로 표시 (react-hot-toast 또는 유사 라이브러리)
- 401 응답 시 자동으로 /login으로 리다이렉트 (axios 인터셉터에서 처리)

### 반응형
- 모바일 대응은 MVP 범위 외이나, 최소한 1024px 이상 데스크톱 화면에서 깨지지 않도록

## 5. README 작성

프로젝트 루트에 README.md 작성:
- 프로젝트 개요 (1~2문장)
- 로컬 실행 방법:
  1. 사전 요구사항 (Python 3.12, Node.js 18+, PostgreSQL, Redis)
  2. backend 설치 및 실행 명령어
  3. frontend 설치 및 실행 명령어
  4. Celery worker 실행 명령어
- 환경변수 설정 방법 (.env.example 기반)

## 완료 기준
- /dashboard에서 본인의 검토 건 목록이 상태·파일 구성과 함께 표시됨
- 다른 사용자의 검토 건은 API 레벨에서 403 반환
- path traversal 공격 방어 코드 존재
- 401 응답 시 /login으로 자동 이동
- README 기반으로 새 환경에서 로컬 실행 가능
```
