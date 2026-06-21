# 제안서 검토 시스템

컨설팅 제안서(PPTX·DOCX·PDF)를 업로드하면 Claude AI가 최상급 표현과 오타를 자동으로 검출해 주는 웹 애플리케이션입니다.

---

## 사전 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.12 이상 |
| Node.js | 18 이상 |
| uv (Python 패키지 관리자) | 최신 |
| Redis | 5.0 이상 (Windows는 포터블 빌드 또는 WSL2 사용) |

---

## 로컬 실행 방법

### 1. 저장소 클론

```bash
git clone <repo-url>
cd "Proposal Review"
```

### 2. 환경변수 설정

```bash
cp backend/.env.example backend/.env
```

`backend/.env` 파일을 열어 아래 값을 설정합니다:

```env
ANTHROPIC_API_KEY=sk-ant-실제키값   # Anthropic Console에서 발급
REDIS_URL=redis://localhost:6379/0   # Redis 주소 (기본값 그대로 사용 가능)
```

### 3. 백엔드 실행

```bash
cd backend

# 의존성 설치
uv sync

# DB 마이그레이션
uv run python -m alembic upgrade head

# FastAPI 서버 시작 (포트 8000)
uv run python -m uvicorn app.main:app --port 8000 --reload
```

### 4. Celery worker 실행 (별도 터미널)

```bash
cd backend
uv run python -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

> Windows에서는 `--pool=solo` 옵션이 필요합니다.

### 5. Redis 실행 (별도 터미널)

**WSL2 환경:**
```bash
sudo service redis-server start
```

**Windows 포터블 빌드 (WSL2 미설치 시):**
```powershell
Start-Process "$env:USERPROFILE\redis-portable\redis-server.exe" `
  -ArgumentList "$env:USERPROFILE\redis-portable\redis.windows.conf" `
  -WindowStyle Hidden
```

> 포터블 빌드 다운로드: https://github.com/tporadowski/redis/releases

### 6. 프론트엔드 실행 (별도 터미널)

```bash
cd frontend

# 의존성 설치
npm install

# 개발 서버 시작 (포트 3000)
npm run dev
```

브라우저에서 http://localhost:3000 으로 접속합니다.

---

## 주요 기능

- **파일 업로드**: PPTX·DOCX·PDF (최대 50MB), 정성·정량·발표본 구분
- **AI 검토**: 최상급 표현 (최초, 최대, 최고 등) 및 오타 자동 검출
- **결과 조회**: 파일별·페이지별 검출 항목, 컨텍스트 텍스트 표시
- **검토 이력**: 모든 검토 건 상태·결과 요약 조회

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 백엔드 | FastAPI, SQLAlchemy (async), SQLite, Alembic |
| AI | Anthropic Claude (claude-sonnet-4-6) |
| 작업 큐 | Celery + Redis |
| 파일 파싱 | python-pptx, python-docx, pdfplumber |
| 프론트엔드 | Next.js 16 (App Router), TypeScript, Tailwind CSS |
