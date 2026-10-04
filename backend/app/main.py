import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import get_supabase
from app.routers import auth, jobs

logger = logging.getLogger(__name__)

app = FastAPI(title="제안서 검토 API")

# Supabase 무료 플랜은 프로젝트에 대한 API 활동이 일정 기간(현재 정책상 약 7일)
# 없으면 자동으로 일시정지(pause)된다. 이 앱의 로그인 사용자가 뜸하면 DB에 전혀
# 접근하지 않는 기간이 생길 수 있으므로, 며칠 주기로 가벼운 쿼리를 날려 활동을
# 유지한다.
SUPABASE_KEEPALIVE_INTERVAL_SECONDS = 60 * 60 * 24 * 3  # 3일


async def _supabase_keepalive_loop():
    while True:
        try:
            get_supabase().table("users").select("id").limit(1).execute()
            logger.info("Supabase keepalive ping ok")
        except Exception:
            logger.exception("Supabase keepalive ping failed")
        await asyncio.sleep(SUPABASE_KEEPALIVE_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_supabase_keepalive():
    asyncio.create_task(_supabase_keepalive_loop())

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://proposal-review-app-1.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(jobs.router)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "서버 오류가 발생했습니다."})


@app.get("/health")
async def health():
    return {"status": "ok"}
