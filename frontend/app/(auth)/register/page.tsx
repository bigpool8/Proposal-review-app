"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import api from "@/lib/api";

function validatePassword(password: string): string | null {
  if (password.length < 6) return "패스워드는 6자 이상이어야 합니다.";
  if (!/[A-Za-z]/.test(password)) return "패스워드에 영문을 포함해야 합니다.";
  if (!/\d/.test(password)) return "패스워드에 숫자를 포함해야 합니다.";
  return null;
}

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const pwError = validatePassword(password);
    if (pwError) {
      setError(pwError);
      return;
    }
    if (password !== confirmPassword) {
      setError("패스워드가 일치하지 않습니다.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await api.post("/api/auth/register", { username, password });
      router.push("/login");
    } catch (err: unknown) {
      const msg =
        err instanceof Error &&
        "response" in err &&
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail;
      setError(msg || "회원가입에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50">
      <h1 className="text-4xl font-bold text-purple-700 mb-8">AI 제안서 검증 시스템</h1>
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-md border border-gray-100 p-12">
        <h1 className="text-3xl font-bold text-gray-900 mb-10">회원가입</h1>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block text-xl font-medium text-gray-700 mb-2">
              아이디
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-3 text-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="block text-xl font-medium text-gray-700 mb-2">
              패스워드
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-3 text-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoComplete="new-password"
              required
            />
            <p className="text-base text-gray-400 mt-2">영문+숫자 포함 6자 이상</p>
          </div>
          <div>
            <label className="block text-xl font-medium text-gray-700 mb-2">
              패스워드 확인
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-3 text-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoComplete="new-password"
              required
            />
          </div>
          {error && (
            <p className="text-red-500 text-base bg-red-50 px-4 py-3 rounded-lg">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white rounded-lg py-3 text-xl font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "처리 중..." : "회원가입"}
          </button>
        </form>
        <p className="mt-6 text-center text-xl text-gray-500">
          이미 계정이 있으신가요?{" "}
          <Link href="/login" className="text-blue-600 hover:underline font-medium">
            로그인
          </Link>
        </p>
      </div>
    </div>
  );
}
