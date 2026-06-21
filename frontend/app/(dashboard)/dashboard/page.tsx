"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { NavBar } from "@/components/NavBar";

interface FileCounts {
  qualitative: number;
  quantitative: number;
  presentation: number;
}

interface Job {
  id: string;
  status: string;
  created_at: string;
  file_counts: FileCounts;
  superlative_count: number;
  typo_count: number;
}

const STATUS: Record<string, { label: string; cls: string; spinner?: boolean }> = {
  draft:      { label: "업로드 중",  cls: "bg-gray-100 text-gray-600" },
  pending:    { label: "검토 대기",  cls: "bg-blue-100 text-blue-600" },
  processing: { label: "검토 중",    cls: "bg-blue-100 text-blue-600", spinner: true },
  completed:  { label: "완료",       cls: "bg-green-100 text-green-700" },
  failed:     { label: "오류",       cls: "bg-red-100 text-red-600" },
};

function fileSummary(c: FileCounts): string {
  const parts: string[] = [];
  if (c.qualitative > 0) parts.push(`정성 ${c.qualitative}개`);
  if (c.quantitative > 0) parts.push(`정량 ${c.quantitative}개`);
  if (c.presentation > 0) parts.push(`발표본 ${c.presentation}개`);
  return parts.length > 0 ? parts.join(" · ") : "파일 없음";
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function DashboardPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const fetchJobs = async () => {
    const { data } = await api.get<Job[]>("/api/jobs");
    const empty = data.filter(
      (j) => j.file_counts.qualitative + j.file_counts.quantitative + j.file_counts.presentation === 0
    );
    if (empty.length > 0) {
      await Promise.allSettled(empty.map((j) => api.post(`/api/jobs/${j.id}/delete`)));
    }
    setJobs(data.filter(
      (j) => j.file_counts.qualitative + j.file_counts.quantitative + j.file_counts.presentation > 0
    ));
  };

  useEffect(() => {
    fetchJobs().finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const needsPoll = jobs.some(
      (j) => j.status === "pending" || j.status === "processing"
    );
    if (!needsPoll) return;
    const timer = setTimeout(() => fetchJobs(), 10000);
    return () => clearTimeout(timer);
  }, [jobs]);

  const handleNew = async () => {
    setCreating(true);
    try {
      const { data } = await api.post("/api/jobs");
      router.push(`/jobs/${data.job_id}/upload`);
    } finally {
      setCreating(false);
    }
  };

  const handleClick = (job: Job) => {
    if (selected.size > 0) return;
    router.push(
      job.status === "draft"
        ? `/jobs/${job.id}/upload`
        : `/jobs/${job.id}/results`
    );
  };

  const toggleSelect = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((prev) =>
      prev.size === jobs.length ? new Set() : new Set(jobs.map((j) => j.id))
    );
  };

  const handleDelete = async () => {
    if (selected.size === 0) return;
    setDeleting(true);
    try {
      await Promise.all([...selected].map((id) => api.post(`/api/jobs/${id}/delete`)));
      const count = selected.size;
      setJobs((prev) => prev.filter((j) => !selected.has(j.id)));
      setSelected(new Set());
      toast.success(`${count}건이 삭제되었습니다.`);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar title={<span className="font-bold text-2xl text-indigo-700">검토 이력</span>} />

      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            {jobs.length > 0 && (
              <>
                <input
                  type="checkbox"
                  checked={selected.size === jobs.length && jobs.length > 0}
                  onChange={toggleSelectAll}
                  className="w-4 h-4 accent-purple-700 cursor-pointer"
                />
                <span className="text-base text-gray-500">전체 선택</span>
              </>
            )}
            {selected.size > 0 && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="bg-red-500 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-red-600 disabled:opacity-50 transition-colors"
              >
                {deleting ? "삭제 중..." : `선택 삭제 (${selected.size})`}
              </button>
            )}
          </div>
          <button
            onClick={handleNew}
            disabled={creating}
            className="bg-blue-600 text-white px-5 py-3 rounded-lg text-base font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {creating ? "생성 중..." : "+ 새 검토 요청"}
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-gray-400 text-base">아직 검토 요청이 없습니다.</p>
            <p className="text-gray-400 text-base mt-1">새 검토 요청을 시작하세요.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {jobs.map((job) => {
              const s = STATUS[job.status] ?? { label: job.status, cls: "bg-gray-100 text-gray-500" };
              const resultSummary =
                job.status === "completed" &&
                (job.superlative_count > 0 || job.typo_count > 0)
                  ? [
                      job.superlative_count > 0 && `최상급 ${job.superlative_count}건`,
                      job.typo_count > 0 && `오타 ${job.typo_count}건`,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : null;
              const isSelected = selected.has(job.id);

              return (
                <div
                  key={job.id}
                  onClick={() => handleClick(job)}
                  className={`bg-white rounded-xl border px-5 py-4 cursor-pointer transition-all ${
                    isSelected
                      ? "border-purple-400 shadow-sm"
                      : "border-gray-200 hover:border-blue-300 hover:shadow-sm"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onClick={(e) => toggleSelect(e, job.id)}
                      onChange={() => {}}
                      className="w-4 h-4 accent-purple-700 cursor-pointer shrink-0"
                    />
                    <div className="flex items-center justify-between flex-1 min-w-0">
                      <div className="min-w-0">
                        <p className="text-sm text-gray-400 mb-0.5">{fmtDate(job.created_at)}</p>
                        <p className="text-base text-gray-700">{fileSummary(job.file_counts)}</p>
                        {resultSummary && (
                          <p className="text-sm text-gray-400 mt-0.5">{resultSummary}</p>
                        )}
                      </div>
                      <span
                        className={`flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full shrink-0 ml-4 ${s.cls}`}
                      >
                        {s.spinner && (
                          <span className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
                        )}
                        {s.label}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
