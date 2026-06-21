"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import api from "@/lib/api";
import { NavBar } from "@/components/NavBar";

type ProposalType = "qualitative" | "quantitative" | "presentation";

interface UploadedFile {
  id: string;
  original_filename: string;
  file_size_bytes: number;
  proposal_type: ProposalType;
}

const ALLOWED_EXTS = [".ppt", ".pptx", ".doc", ".docx", ".pdf"];
const MAX_SIZE = 2 * 1024 * 1024 * 1024;

function fmtBytes(b: number): string {
  return b < 1024 * 1024
    ? `${(b / 1024).toFixed(1)} KB`
    : `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

// ── 업로드 섹션 컴포넌트 ────────────────────────────────────
interface SectionProps {
  jobId: string;
  type: ProposalType;
  label: string;
  files: UploadedFile[];
  multiple: boolean;
  onUploaded: (f: UploadedFile) => void;
  onDeleted: (id: string) => void;
}

function UploadSection({ jobId, type, label, files, multiple, onUploaded, onDeleted }: SectionProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const processFiles = useCallback(async (selected: File[]) => {
    setError("");
    setUploading(true);

    for (const file of selected) {
      const ext = "." + (file.name.split(".").pop()?.toLowerCase() ?? "");
      if (!ALLOWED_EXTS.includes(ext)) {
        setError(`허용되지 않는 파일 형식입니다: ${file.name}`);
        continue;
      }
      if (file.size > MAX_SIZE) {
        setError(`파일 크기가 2GB를 초과합니다: ${file.name}`);
        continue;
      }

      const form = new FormData();
      form.append("file", file);
      form.append("proposal_type", type);

      try {
        const { data } = await api.post(`/api/jobs/${jobId}/files`, form);
        onUploaded({
          id: data.file_id,
          original_filename: data.original_filename,
          file_size_bytes: file.size,
          proposal_type: type,
        });
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail;
        setError(detail || "업로드에 실패했습니다.");
      }
    }

    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
  }, [jobId, type, onUploaded]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const all = Array.from(e.target.files ?? []);
    processFiles(multiple ? all : all.slice(0, 1));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const all = Array.from(e.dataTransfer.files);
    processFiles(multiple ? all : all.slice(0, 1));
  };

  const handleDelete = async (fileId: string) => {
    try {
      await api.delete(`/api/jobs/${jobId}/files/${fileId}`);
      onDeleted(fileId);
      setError("");
    } catch {
      setError("파일 삭제에 실패했습니다.");
    }
  };

  const canUpload = multiple || files.length === 0;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="font-medium text-base text-gray-900">{label}</h3>
        {!multiple && (
          <span className="text-sm text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
            1개
          </span>
        )}
        {multiple && (
          <span className="text-sm text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
            다중 파일
          </span>
        )}
      </div>

      {canUpload && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => !uploading && inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors select-none
            ${dragging
              ? "border-blue-400 bg-blue-50"
              : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
            }`}
        >
          <p className="text-base text-gray-500">
            {uploading ? "업로드 중..." : "클릭하거나 파일을 드래그하세요"}
          </p>
          <p className="text-sm text-gray-400 mt-1">
            {ALLOWED_EXTS.join(", ")} · 최대 2GB
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={ALLOWED_EXTS.join(",")}
            multiple={multiple}
            className="hidden"
            onChange={handleChange}
          />
        </div>
      )}

      {error && (
        <p className="text-red-500 text-sm mt-2 bg-red-50 px-3 py-1.5 rounded-lg">
          {error}
        </p>
      )}

      {files.length > 0 && (
        <ul className="mt-3 space-y-2">
          {files.map((f) => (
            <li
              key={f.id}
              className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2.5"
            >
              <div className="min-w-0 mr-4">
                <p className="text-base text-gray-800 truncate">{f.original_filename}</p>
                <p className="text-sm text-gray-400">{fmtBytes(f.file_size_bytes)}</p>
              </div>
              <button
                onClick={() => handleDelete(f.id)}
                className="flex-shrink-0 text-sm text-red-500 hover:text-red-700 hover:underline"
              >
                삭제
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── 확인 모달 ────────────────────────────────────────────
interface ModalProps {
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}

function ConfirmModal({ onConfirm, onCancel, loading }: ModalProps) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-xl">
        <h3 className="font-semibold text-base text-gray-900 mb-2">검토를 시작할까요?</h3>
        <p className="text-base text-gray-500 mb-5">
          검토 시작 후에는 파일 변경이 불가합니다.
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={loading}
            className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-base hover:bg-gray-50 disabled:opacity-50"
          >
            취소
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-base font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "처리 중..." : "시작"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 메인 페이지 ──────────────────────────────────────────
export default function UploadPage() {
  const router = useRouter();
  const params = useParams();
  const jobId = params.id as string;

  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api
      .get(`/api/jobs/${jobId}`)
      .then((r) => setFiles(r.data.files ?? []))
      .catch(() => router.push("/dashboard"))
      .finally(() => setLoading(false));
  }, [jobId, router]);

  const byType = (t: ProposalType) => files.filter((f) => f.proposal_type === t);

  const handleUploaded = (f: UploadedFile) => setFiles((prev) => [...prev, f]);
  const handleDeleted = (id: string) =>
    setFiles((prev) => prev.filter((f) => f.id !== id));

  const handleStart = async () => {
    setStarting(true);
    try {
      await api.post(`/api/jobs/${jobId}/start`);
      router.push(`/jobs/${jobId}/results`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      alert(detail || "검토 시작에 실패했습니다.");
      setStarting(false);
      setShowModal(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-gray-400">로딩 중...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar title={<span className="font-bold text-2xl text-indigo-700">제안서 업로드</span>}>
        <button
          onClick={() => router.push("/dashboard")}
          className="text-lg font-bold text-purple-700 hover:text-purple-900"
        >
          ← 검토 이력
        </button>
      </NavBar>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-4">
        <UploadSection
          jobId={jobId} type="qualitative" label="정성제안서"
          files={byType("qualitative")} multiple={true}
          onUploaded={handleUploaded} onDeleted={handleDeleted}
        />
        <UploadSection
          jobId={jobId} type="quantitative" label="정량제안서"
          files={byType("quantitative")} multiple={true}
          onUploaded={handleUploaded} onDeleted={handleDeleted}
        />
        <UploadSection
          jobId={jobId} type="presentation" label="발표본"
          files={byType("presentation")} multiple={false}
          onUploaded={handleUploaded} onDeleted={handleDeleted}
        />

        <div className="pt-2">
          <button
            onClick={() => setShowModal(true)}
            disabled={files.length === 0}
            className="w-full bg-blue-600 text-white rounded-lg py-3 text-base font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            검토 시작
          </button>
          {files.length === 0 && (
            <p className="text-base text-gray-900 text-center mt-2">
              파일을 1개 이상 업로드하면 검토를 시작할 수 있습니다.
            </p>
          )}
        </div>
      </div>

      {showModal && (
        <ConfirmModal
          onConfirm={handleStart}
          onCancel={() => setShowModal(false)}
          loading={starting}
        />
      )}
    </div>
  );
}
