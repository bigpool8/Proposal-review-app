"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface NavBarProps {
  children?: React.ReactNode;
  title?: React.ReactNode;
}

export function NavBar({ children, title }: NavBarProps) {
  const router = useRouter();
  const [username, setUsername] = useState("");

  useEffect(() => {
    setUsername(localStorage.getItem("username") ?? "");
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("username");
    router.push("/login");
  };

  return (
    <nav className="relative bg-white border-b border-gray-200 px-6 py-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        {children ?? (
          <span className="font-bold text-2xl text-purple-700">AI 제안서 검증 시스템</span>
        )}
      </div>
      {title && (
        <div className="absolute left-1/2 -translate-x-1/2">
          {title}
        </div>
      )}
      <div className="flex items-center gap-4">
        {username && (
          <span className="text-base font-bold text-green-800">{username}</span>
        )}
        <button
          onClick={handleLogout}
          className="text-base font-bold text-purple-700 hover:text-purple-900"
        >
          로그아웃
        </button>
      </div>
    </nav>
  );
}
