"use client";

import { useState, useEffect } from "react";
import { Toaster } from "react-hot-toast";

export function ToastProvider() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  if (!mounted) return null;
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 4000,
        style: { fontSize: "14px", maxWidth: "420px" },
      }}
    />
  );
}
