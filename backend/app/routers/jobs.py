import os
import uuid

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.review import ReviewFile, ReviewJob, ReviewResult
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.job import FileCounts, FileResponse, FileUploadResponse, JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

ALLOWED_EXTENSIONS = {".ppt", ".pptx", ".doc", ".docx", ".pdf"}
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
CHUNK_SIZE = 1024 * 1024  # 1 MB
UPLOAD_BASE = "uploads"
PROPOSAL_TYPES = {"qualitative", "quantitative", "presentation"}


def _build_response(job: ReviewJob, *, with_results: bool = False) -> JobResponse:
    counts = FileCounts(
        qualitative=sum(1 for f in job.files if f.proposal_type == "qualitative"),
        quantitative=sum(1 for f in job.files if f.proposal_type == "quantitative"),
        presentation=sum(1 for f in job.files if f.proposal_type == "presentation"),
    )
    sup = typo = 0
    if with_results:
        for f in job.files:
            for r in f.results:
                if r.category == "superlative":
                    sup += 1
                elif r.category == "typo":
                    typo += 1
    return JobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        files=[
            FileResponse(
                id=f.id,
                proposal_type=f.proposal_type,
                original_filename=f.original_filename,
                file_size_bytes=f.file_size_bytes,
                uploaded_at=f.uploaded_at,
            )
            for f in job.files
        ],
        file_counts=counts,
        superlative_count=sup,
        typo_count=typo,
    )


async def _get_job(
    job_id: str, user_id: str, db: AsyncSession, *, with_files: bool = False
) -> ReviewJob:
    q = select(ReviewJob).where(ReviewJob.id == job_id)
    if with_files:
        q = q.options(selectinload(ReviewJob.files))
    result = await db.execute(q)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="검토 건을 찾을 수 없습니다.")
    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return job


# ── 검토 건 생성 ──────────────────────────────────────────
@router.post("", status_code=201)
async def create_job(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = ReviewJob(user_id=current_user.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id}


# ── 검토 건 목록 ──────────────────────────────────────────
@router.get("", response_model=list[JobResponse])
async def list_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReviewJob)
        .where(ReviewJob.user_id == current_user.id)
        .options(selectinload(ReviewJob.files).selectinload(ReviewFile.results))
        .order_by(ReviewJob.created_at.desc())
    )
    return [_build_response(j, with_results=True) for j in result.scalars().all()]


# ── 검토 건 상세 ──────────────────────────────────────────
@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job(job_id, current_user.id, db, with_files=True)
    return _build_response(job)


# ── 파일 업로드 ───────────────────────────────────────────
@router.post("/{job_id}/files", status_code=201, response_model=FileUploadResponse)
async def upload_file(
    job_id: str,
    file: UploadFile = File(...),
    proposal_type: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if proposal_type not in PROPOSAL_TYPES:
        raise HTTPException(status_code=400, detail="올바르지 않은 제안서 종류입니다.")

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 파일 형식입니다. 허용 형식: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    job = await _get_job(job_id, current_user.id, db)
    if job.status != "draft":
        raise HTTPException(status_code=409, detail="이미 검토가 시작된 건은 파일을 수정할 수 없습니다.")

    # path traversal 방지: basename만 사용
    safe_name = os.path.basename(filename) or f"file{ext}"
    file_id = str(uuid.uuid4())
    dir_path = os.path.join(UPLOAD_BASE, job_id, file_id)
    os.makedirs(dir_path, exist_ok=True)

    # 절대 경로 검증
    abs_base = os.path.abspath(UPLOAD_BASE)
    abs_path = os.path.abspath(os.path.join(dir_path, safe_name))
    if not abs_path.startswith(abs_base):
        raise HTTPException(status_code=400, detail="올바르지 않은 파일명입니다.")

    # 청크 단위 스트리밍 저장 (2GB 대응)
    total_size = 0
    async with aiofiles.open(abs_path, "wb") as out:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_FILE_SIZE:
                await out.close()
                os.remove(abs_path)
                raise HTTPException(status_code=400, detail="파일 크기가 2GB를 초과합니다.")
            await out.write(chunk)

    review_file = ReviewFile(
        id=file_id,
        job_id=job_id,
        proposal_type=proposal_type,
        original_filename=safe_name,
        storage_path=abs_path,
        file_size_bytes=total_size,
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(review_file)
    await db.commit()

    return FileUploadResponse(
        file_id=file_id,
        original_filename=safe_name,
        proposal_type=proposal_type,
    )


# ── 파일 삭제 ─────────────────────────────────────────────
@router.delete("/{job_id}/files/{file_id}", status_code=204)
async def delete_file(
    job_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job(job_id, current_user.id, db)
    if job.status != "draft":
        raise HTTPException(status_code=409, detail="이미 검토가 시작된 건은 파일을 삭제할 수 없습니다.")

    result = await db.execute(
        select(ReviewFile).where(
            ReviewFile.id == file_id, ReviewFile.job_id == job_id
        )
    )
    rf = result.scalar_one_or_none()
    if not rf:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    if os.path.exists(rf.storage_path):
        os.remove(rf.storage_path)
    parent = os.path.dirname(rf.storage_path)
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)

    await db.delete(rf)
    await db.commit()


# ── 검토 건 삭제 ─────────────────────────────────────────
@router.post("/{job_id}/delete", status_code=204)
async def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 소유권 확인
    job = await _get_job(job_id, current_user.id, db, with_files=True)

    # 디스크 파일 삭제
    for f in job.files:
        if os.path.exists(f.storage_path):
            os.remove(f.storage_path)
        parent = os.path.dirname(f.storage_path)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)

    file_ids = [f.id for f in job.files]

    # DB 삭제: 결과 → 파일 → job 순서
    if file_ids:
        await db.execute(delete(ReviewResult).where(ReviewResult.file_id.in_(file_ids)))
    await db.execute(delete(ReviewFile).where(ReviewFile.job_id == job_id))
    await db.execute(delete(ReviewJob).where(ReviewJob.id == job_id))
    await db.commit()

    job_dir = os.path.join(UPLOAD_BASE, job_id)
    if os.path.isdir(job_dir) and not os.listdir(job_dir):
        os.rmdir(job_dir)


# ── 검토 시작 ─────────────────────────────────────────────
@router.post("/{job_id}/start")
async def start_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.workers.review_task import run_review

    job = await _get_job(job_id, current_user.id, db, with_files=True)
    if job.status != "draft":
        raise HTTPException(status_code=409, detail="이미 검토가 시작되었습니다.")
    if not job.files:
        raise HTTPException(status_code=400, detail="파일을 먼저 업로드하세요.")

    task = run_review.delay(job.id)
    job.status = "pending"
    job.celery_task_id = task.id
    await db.commit()
    return {"job_id": job.id, "status": "pending"}


# ── 검토 결과 조회 ────────────────────────────────────────
_PROPOSAL_LABELS = {
    "qualitative": "정성제안서",
    "quantitative": "정량제안서",
    "presentation": "발표본",
}
_PROPOSAL_ORDER = ["qualitative", "quantitative", "presentation"]


@router.get("/{job_id}/results")
async def get_job_results(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReviewJob)
        .where(ReviewJob.id == job_id)
        .options(selectinload(ReviewJob.files).selectinload(ReviewFile.results))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="검토 건을 찾을 수 없습니다.")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    files_by_type: dict[str, list] = {}
    for f in job.files:
        files_by_type.setdefault(f.proposal_type, []).append(f)

    total_superlative = 0
    total_typo = 0
    files_with_issues = 0
    proposal_types = []

    for ptype in _PROPOSAL_ORDER:
        if ptype not in files_by_type:
            continue
        file_results = []
        for f in files_by_type[ptype]:
            items = sorted(f.results, key=lambda r: (r.page_number, r.category))
            sup = sum(1 for r in items if r.category == "superlative")
            typo = sum(1 for r in items if r.category == "typo")
            total_superlative += sup
            total_typo += typo
            if sup + typo > 0:
                files_with_issues += 1
            file_results.append({
                "file_id": f.id,
                "original_filename": f.original_filename,
                "total_pages": f.total_pages,
                "parse_error": f.parse_error,
                "superlative_count": sup,
                "typo_count": typo,
                "results": [
                    {
                        "id": r.id,
                        "category": r.category,
                        "detected_text": r.detected_text,
                        "suggestion": r.suggestion,
                        "page_number": r.page_number,
                        "context": r.context,
                    }
                    for r in items
                ],
            })
        proposal_types.append({
            "type": ptype,
            "label": _PROPOSAL_LABELS[ptype],
            "files": file_results,
        })

    return {
        "job_id": job_id,
        "status": job.status,
        "error_message": job.error_message,
        "summary": {
            "total_superlative": total_superlative,
            "total_typo": total_typo,
            "files_with_issues": files_with_issues,
        },
        "proposal_types": proposal_types,
    }


# ── 검토 재시도 ────────────────────────────────────────────
@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.workers.review_task import run_review

    job = await _get_job(job_id, current_user.id, db, with_files=True)
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="failed 상태인 검토 건만 재시도할 수 있습니다.")

    file_ids = [f.id for f in job.files]
    await db.execute(delete(ReviewResult).where(ReviewResult.file_id.in_(file_ids)))
    await db.execute(
        update(ReviewFile)
        .where(ReviewFile.job_id == job_id)
        .values(parse_error=None, total_pages=None)
    )

    task = run_review.delay(job.id)
    job.status = "pending"
    job.celery_task_id = task.id
    job.error_message = None
    await db.commit()
    return {"job_id": job_id, "status": "pending"}


# ── 검토 상태 조회 ─────────────────────────────────────────
@router.get("/{job_id}/status")
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job(job_id, current_user.id, db, with_files=True)
    return {
        "status": job.status,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message,
        "file_statuses": [
            {
                "file_id": f.id,
                "original_filename": f.original_filename,
                "parse_error": f.parse_error,
                "total_pages": f.total_pages,
            }
            for f in job.files
        ],
    }
