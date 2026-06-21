import os
import uuid

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from supabase import Client

from app.database import get_supabase
from app.routers.auth import get_current_user
from app.schemas.job import FileCounts, FileResponse, FileUploadResponse, JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

ALLOWED_EXTENSIONS = {".ppt", ".pptx", ".doc", ".docx", ".pdf"}
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
CHUNK_SIZE = 1024 * 1024  # 1 MB
UPLOAD_BASE = "uploads"
PROPOSAL_TYPES = {"qualitative", "quantitative", "presentation"}


def _build_response(job: dict, *, with_results: bool = False) -> JobResponse:
    files = job.get("review_files") or []
    counts = FileCounts(
        qualitative=sum(1 for f in files if f["proposal_type"] == "qualitative"),
        quantitative=sum(1 for f in files if f["proposal_type"] == "quantitative"),
        presentation=sum(1 for f in files if f["proposal_type"] == "presentation"),
    )
    sup = typo = 0
    if with_results:
        for f in files:
            for r in (f.get("review_results") or []):
                if r["category"] == "superlative":
                    sup += 1
                elif r["category"] == "typo":
                    typo += 1
    return JobResponse(
        id=job["id"],
        status=job["status"],
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        files=[
            FileResponse(
                id=f["id"],
                proposal_type=f["proposal_type"],
                original_filename=f["original_filename"],
                file_size_bytes=f["file_size_bytes"],
                uploaded_at=f["uploaded_at"],
            )
            for f in files
        ],
        file_counts=counts,
        superlative_count=sup,
        typo_count=typo,
    )


def _get_job(
    job_id: str,
    user_id: str,
    sb: Client,
    *,
    with_files: bool = False,
    with_results: bool = False,
) -> dict:
    if with_results:
        select_str = "*, review_files(*, review_results(*))"
    elif with_files:
        select_str = "*, review_files(*)"
    else:
        select_str = "*"
    res = sb.table("proposal_review").select(select_str).eq("id", job_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="검토 건을 찾을 수 없습니다.")
    job = res.data[0]
    if job["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return job


# ── 검토 건 생성 ──────────────────────────────────────────
@router.post("", status_code=201)
def create_job(
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    res = sb.table("proposal_review").insert({
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "status": "draft",
    }).execute()
    return {"job_id": res.data[0]["id"]}


# ── 검토 건 목록 ──────────────────────────────────────────
@router.get("", response_model=list[JobResponse])
def list_jobs(
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    res = sb.table("proposal_review").select(
        "*, review_files(*, review_results(*))"
    ).eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
    return [_build_response(j, with_results=True) for j in (res.data or [])]


# ── 검토 건 상세 ──────────────────────────────────────────
@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    job = _get_job(job_id, current_user["id"], sb, with_files=True)
    return _build_response(job)


# ── 파일 업로드 ───────────────────────────────────────────
@router.post("/{job_id}/files", status_code=201, response_model=FileUploadResponse)
async def upload_file(
    job_id: str,
    file: UploadFile = File(...),
    proposal_type: str = Form(...),
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
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

    job = _get_job(job_id, current_user["id"], sb)
    if job["status"] != "draft":
        raise HTTPException(status_code=409, detail="이미 검토가 시작된 건은 파일을 수정할 수 없습니다.")

    safe_name = os.path.basename(filename) or f"file{ext}"
    file_id = str(uuid.uuid4())
    dir_path = os.path.join(UPLOAD_BASE, job_id, file_id)
    os.makedirs(dir_path, exist_ok=True)

    abs_base = os.path.abspath(UPLOAD_BASE)
    abs_path = os.path.abspath(os.path.join(dir_path, safe_name))
    if not abs_path.startswith(abs_base):
        raise HTTPException(status_code=400, detail="올바르지 않은 파일명입니다.")

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

    sb.table("review_files").insert({
        "id": file_id,
        "job_id": job_id,
        "proposal_type": proposal_type,
        "original_filename": safe_name,
        "storage_path": abs_path,
        "file_size_bytes": total_size,
        "mime_type": file.content_type or "application/octet-stream",
    }).execute()

    return FileUploadResponse(
        file_id=file_id,
        original_filename=safe_name,
        proposal_type=proposal_type,
    )


# ── 파일 삭제 ─────────────────────────────────────────────
@router.delete("/{job_id}/files/{file_id}", status_code=204)
def delete_file(
    job_id: str,
    file_id: str,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    job = _get_job(job_id, current_user["id"], sb)
    if job["status"] != "draft":
        raise HTTPException(status_code=409, detail="이미 검토가 시작된 건은 파일을 삭제할 수 없습니다.")

    res = sb.table("review_files").select("*").eq("id", file_id).eq("job_id", job_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    rf = res.data[0]

    if os.path.exists(rf["storage_path"]):
        os.remove(rf["storage_path"])
    parent = os.path.dirname(rf["storage_path"])
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)

    sb.table("review_files").delete().eq("id", file_id).execute()


# ── 검토 건 삭제 ─────────────────────────────────────────
@router.post("/{job_id}/delete", status_code=204)
def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    job = _get_job(job_id, current_user["id"], sb, with_files=True)
    files = job.get("review_files") or []

    # 로컬 파일 정리 (Railway 임시 파일시스템 — 실패해도 무시)
    for f in files:
        try:
            path = f.get("storage_path") or ""
            if path and os.path.exists(path):
                os.remove(path)
            parent = os.path.dirname(path) if path else ""
            if parent and os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass

    # proposal_review 삭제 → CASCADE로 review_files, review_results 자동 삭제
    sb.table("proposal_review").delete().eq("id", job_id).execute()


# ── 검토 시작 ─────────────────────────────────────────────
@router.post("/{job_id}/start")
def start_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    from app.workers.review_task import run_review_sync

    job = _get_job(job_id, current_user["id"], sb, with_files=True)
    if job["status"] != "draft":
        raise HTTPException(status_code=409, detail="이미 검토가 시작되었습니다.")
    files = job.get("review_files") or []
    if not files:
        raise HTTPException(status_code=400, detail="파일을 먼저 업로드하세요.")

    sb.table("proposal_review").update({"status": "pending"}).eq("id", job_id).execute()
    background_tasks.add_task(run_review_sync, job_id)
    return {"job_id": job_id, "status": "pending"}


# ── 검토 결과 조회 ────────────────────────────────────────
_PROPOSAL_LABELS = {
    "qualitative": "정성제안서",
    "quantitative": "정량제안서",
    "presentation": "발표본",
}
_PROPOSAL_ORDER = ["qualitative", "quantitative", "presentation"]


@router.get("/{job_id}/results")
def get_job_results(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    job = _get_job(job_id, current_user["id"], sb, with_results=True)
    files = job.get("review_files") or []

    files_by_type: dict[str, list] = {}
    for f in files:
        files_by_type.setdefault(f["proposal_type"], []).append(f)

    total_superlative = 0
    total_typo = 0
    files_with_issues = 0
    proposal_types = []

    for ptype in _PROPOSAL_ORDER:
        if ptype not in files_by_type:
            continue
        file_results = []
        for f in files_by_type[ptype]:
            items = sorted(
                f.get("review_results") or [],
                key=lambda r: (r["page_number"], r["category"]),
            )
            sup = sum(1 for r in items if r["category"] == "superlative")
            typo = sum(1 for r in items if r["category"] == "typo")
            total_superlative += sup
            total_typo += typo
            if sup + typo > 0:
                files_with_issues += 1
            file_results.append({
                "file_id": f["id"],
                "original_filename": f["original_filename"],
                "total_pages": f.get("total_pages"),
                "parse_error": f.get("parse_error"),
                "superlative_count": sup,
                "typo_count": typo,
                "results": [
                    {
                        "id": r["id"],
                        "category": r["category"],
                        "detected_text": r["detected_text"],
                        "suggestion": r.get("suggestion"),
                        "page_number": r["page_number"],
                        "context": r.get("context"),
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
        "status": job["status"],
        "error_message": job.get("error_message"),
        "summary": {
            "total_superlative": total_superlative,
            "total_typo": total_typo,
            "files_with_issues": files_with_issues,
        },
        "proposal_types": proposal_types,
    }


# ── 검토 재시도 ────────────────────────────────────────────
@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    from app.workers.review_task import run_review_sync

    job = _get_job(job_id, current_user["id"], sb, with_files=True)
    if job["status"] != "failed":
        raise HTTPException(status_code=409, detail="failed 상태인 검토 건만 재시도할 수 있습니다.")

    file_ids = [f["id"] for f in (job.get("review_files") or [])]
    if file_ids:
        sb.table("review_results").delete().in_("file_id", file_ids).execute()
        sb.table("review_files").update({"parse_error": None, "total_pages": None}).in_("id", file_ids).execute()

    sb.table("proposal_review").update({
        "status": "pending",
        "error_message": None,
    }).eq("id", job_id).execute()
    background_tasks.add_task(run_review_sync, job_id)
    return {"job_id": job_id, "status": "pending"}


# ── 검토 상태 조회 ─────────────────────────────────────────
@router.get("/{job_id}/status")
def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    sb: Client = Depends(get_supabase),
):
    job = _get_job(job_id, current_user["id"], sb, with_files=True)
    files = job.get("review_files") or []
    return {
        "status": job["status"],
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "error_message": job.get("error_message"),
        "file_statuses": [
            {
                "file_id": f["id"],
                "original_filename": f["original_filename"],
                "parse_error": f.get("parse_error"),
                "total_pages": f.get("total_pages"),
            }
            for f in files
        ],
    }
