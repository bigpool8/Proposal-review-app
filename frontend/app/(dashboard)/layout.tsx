"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import api from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [verified, setVerified] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    api
      .get("/api/auth/me")
      .then((res) => {
        if (res.data?.username) {
          localStorage.setItem("username", res.data.username);
        }
        setVerified(true);
      })
      .catch(() => {
        localStorage.removeItem("access_token");
        router.replace("/login");
      });
  }, [router]);

  if (!verified) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-gray-400">로딩 중...</p>
      </div>
    );
  }

  return <>{children}</>;
}
