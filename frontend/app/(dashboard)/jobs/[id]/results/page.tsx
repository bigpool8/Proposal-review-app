"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import api from "@/lib/api";
import { NavBar } from "@/components/NavBar";

// ── 타입 ──────────────────────────────────────────────────
interface ResultItem {
  id: string;
  category: "superlative" | "typo";
  detected_text: string;
  suggestion: string | null;
  page_number: number;
  context: string | null;
}

interface FileResult {
  file_id: string;
  original_filename: string;
  total_pages: number | null;
  parse_error: string | null;
  superlative_count: number;
  typo_count: number;
  results: ResultItem[];
}

interface ProposalSection {
  type: string;
  label: string;
  files: FileResult[];
}

interface JobData {
  job_id: string;
  status: string;
  error_message?: string | null;
  summary: { total_superlative: number; total_typo: number; files_with_issues: number };
  proposal_types: ProposalSection[];
}

// ── 컨텍스트 강조 ─────────────────────────────────────────
function HighlightContext({
  context,
  detectedText,
}: {
  context: string | null;
  detectedText: string;
}) {
  if (!context) return <span className="text-gray-400 italic">컨텍스트 없음</span>;
  const lc = context.toLowerCase();
  const lt = detectedText.toLowerCase();
  const idx = lc.indexOf(lt);
  if (idx === -1) return <span>{context}</span>;
  return (
    <>
      {context.slice(0, idx)}
      <strong className="font-semibold">
        {context.slice(idx, idx + detectedText.length)}
      </strong>
      {context.slice(idx + detectedText.length)}
    </>
  );
}

// ── 파일 카드 (아코디언) ──────────────────────────────────
function FileCard({ file }: { file: FileResult }) {
  const [open, setOpen] = useState(true);
  const superlatives = file.results.filter((r) => r.category === "superlative");
  const typos = file.results.filter((r) => r.category === "typo");
  const hasIssues = file.results.length > 0;

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
      {/* 헤더 */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-gray-900 text-base truncate">
            {file.original_filename}
          </span>
          {file.total_pages != null && (
            <span className="text-sm text-gray-400 shrink-0">{file.total_pages}p</span>
          )}
        </div>
        <div className="flex items-center gap-2 ml-4 shrink-0">
          {file.superlative_count > 0 && (
            <span className="text-sm font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">
              최상급 {file.superlative_count}건
            </span>
          )}
          {file.typo_count > 0 && (
            <span className="text-sm font-medium text-red-700 bg-red-50 px-2 py-0.5 rounded-full">
              오타 {file.typo_count}건
            </span>
          )}
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-100">
          {/* 파싱 오류 배너 */}
          {file.parse_error && (
            <div className="bg-yellow-50 border-b border-yellow-100 px-5 py-3">
              <p className="text-sm text-yellow-800">
                <span className="font-semibold">파싱 오류:</span> {file.parse_error}
              </p>
            </div>
          )}

          {/* 결과 없음 */}
          {!hasIssues && !file.parse_error && (
            <div className="px-5 py-8 text-center text-base text-gray-400">
              검출된 항목 없음
            </div>
          )}

          {/* 최상급 표현 */}
          {superlatives.length > 0 && (
            <div className={typos.length > 0 ? "border-b border-gray-100" : ""}>
              <div className="px-5 py-2 bg-amber-50 border-b border-amber-100 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
                <h4 className="text-sm font-semibold text-amber-800">
                  최상급 표현 ({superlatives.length}건)
                </h4>
              </div>
              <ul>
                {superlatives.map((item, i) => (
                  <li
                    key={item.id}
                    className={`px-5 py-3 bg-amber-50/40 ${i < superlatives.length - 1 ? "border-b border-amber-50" : ""}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className="text-sm text-amber-600 font-medium whitespace-nowrap mt-0.5 shrink-0">
                        [{item.page_number}페이지]
                      </span>
                      <div className="min-w-0">
                        <p className="text-base text-gray-800 leading-relaxed">
                          <HighlightContext
                            context={item.context}
                            detectedText={item.detected_text}
                          />
                        </p>
                        <span className="inline-block mt-1.5 text-sm font-medium text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full">
                          검토 필요
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 오타 */}
          {typos.length > 0 && (
            <div>
              <div className="px-5 py-2 bg-red-50 border-b border-red-100 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
                <h4 className="text-sm font-semibold text-red-800">
                  오타 ({typos.length}건)
                </h4>
              </div>
              <ul>
                {typos.map((item, i) => (
                  <li
                    key={item.id}
                    className={`px-5 py-3 bg-red-50/40 ${i < typos.length - 1 ? "border-b border-red-50" : ""}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className="text-sm text-red-600 font-medium whitespace-nowrap mt-0.5 shrink-0">
                        [{item.page_number}페이지]
                      </span>
                      <div className="min-w-0">
                        <p className="text-base text-gray-800 leading-relaxed">
                          <HighlightContext
                            context={item.context}
                            detectedText={item.detected_text}
                          />
                        </p>
                        {item.suggestion && (
                          <p className="mt-1.5 text-sm text-red-700">
                            → 수정 제안:{" "}
                            <span className="font-medium">{item.suggestion}</span>
                          </p>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 메인 페이지 ──────────────────────────────────────────
export default function ResultsPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.id as string;

  const [jobData, setJobData] = useState<JobData | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [pollKey, setPollKey] = useState(0);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const { data } = await api.get<JobData>(`/api/jobs/${jobId}/results`);
        if (!alive) return;
        setJobData(data);
        setInitialLoading(false);
        if (data.status === "pending" || data.status === "processing") {
          timer = setTimeout(poll, 5000);
        }
      } catch {
        if (alive) router.push("/dashboard");
      }
    }

    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId, pollKey, router]);

  const handleRetry = useCallback(async () => {
    setRetrying(true);
    try {
      await api.post(`/api/jobs/${jobId}/retry`);
      setJobData((prev) => (prev ? { ...prev, status: "pending" } : null));
      setPollKey((k) => k + 1);
    } catch {
      // 오류 무시 - 폴링이 실패 상태를 반영
    } finally {
      setRetrying(false);
    }
  }, [jobId]);

  // 초기 로딩
  if (initialLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  const status = jobData?.status ?? "unknown";

  // ── 처리 중 ──────────────────────────────────────────────
  if (status === "pending" || status === "processing") {
    return (
      <div className="min-h-screen bg-gray-50">
        <NavBar />
        <div className="flex flex-col items-center justify-center py-36">
          <div className="animate-spin h-10 w-10 border-2 border-blue-500 border-t-transparent rounded-full mb-5" />
          <p className="text-gray-700 font-medium text-base">검토 중입니다.</p>
          <p className="text-gray-400 text-base mt-1.5">
            파일 크기에 따라 수 분이 소요될 수 있습니다.
          </p>
        </div>
      </div>
    );
  }

  // ── 오류 ─────────────────────────────────────────────────
  if (status === "failed") {
    return (
      <div className="min-h-screen bg-gray-50">
        <NavBar />
        <div className="max-w-lg mx-auto px-6 py-24 text-center">
          <p className="text-red-600 font-semibold text-lg mb-3">
            검토 중 오류가 발생했습니다
          </p>
          {jobData?.error_message && (
            <p className="text-gray-500 text-base mb-6 bg-red-50 border border-red-100 px-4 py-3 rounded-xl">
              {jobData.error_message}
            </p>
          )}
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg text-base font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {retrying ? "재시도 중..." : "재시도"}
          </button>
        </div>
      </div>
    );
  }

  // ── 완료 ─────────────────────────────────────────────────
  const { summary, proposal_types } = jobData!;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 네비게이션 */}
      <NavBar title={
        <div className="flex items-center gap-2">
          <span className="font-bold text-2xl text-indigo-700">검토 결과</span>
          <span className="text-sm font-medium bg-green-100 text-green-700 px-2 py-0.5 rounded-full">완료</span>
        </div>
      }>
        <button
          onClick={() => router.push("/dashboard")}
          className="text-lg font-bold text-purple-700 hover:text-purple-900"
        >
          ← 검토 이력
        </button>
      </NavBar>

      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        {/* 요약 카드 */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white rounded-xl border border-gray-200 px-5 py-4">
            <p className="text-sm text-gray-500 mb-1">최상급 표현</p>
            <p className="text-3xl font-bold text-amber-500">{summary.total_superlative}</p>
            <p className="text-sm text-gray-400 mt-0.5">건 검출</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 px-5 py-4">
            <p className="text-sm text-gray-500 mb-1">오타</p>
            <p className="text-3xl font-bold text-red-500">{summary.total_typo}</p>
            <p className="text-sm text-gray-400 mt-0.5">건 검출</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 px-5 py-4">
            <p className="text-sm text-gray-500 mb-1">검토 파일</p>
            <p className="text-3xl font-bold text-blue-500">{summary.files_with_issues}</p>
            <p className="text-sm text-gray-400 mt-0.5">개 파일에서 검출</p>
          </div>
        </div>

        {/* 제안서 종류별 섹션 */}
        {proposal_types.map((pt) => {
          const totalIssues = pt.files.reduce(
            (s, f) => s + f.superlative_count + f.typo_count,
            0
          );
          return (
            <section key={pt.type}>
              <div className="flex items-center gap-3 mb-3">
                <h2 className="font-semibold text-base text-gray-900">{pt.label}</h2>
                <span className="text-sm text-gray-400">{pt.files.length}개 파일</span>
                {totalIssues > 0 && (
                  <span className="text-sm font-medium text-gray-600 bg-gray-100 px-2 py-0.5 rounded-full">
                    총 {totalIssues}건 검출
                  </span>
                )}
              </div>
              <div className="space-y-3">
                {pt.files.map((file) => (
                  <FileCard key={file.file_id} file={file} />
                ))}
              </div>
            </section>
          );
        })}

        {proposal_types.length === 0 && (
          <div className="text-center py-16 text-gray-400 text-base">
            검토된 파일이 없습니다.
          </div>
        )}
      </div>
    </div>
  );
}
