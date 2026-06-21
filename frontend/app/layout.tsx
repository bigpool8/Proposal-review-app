import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { ToastProvider } from "@/components/ToastProvider";

const geist = Geist({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AI 제안서 검증 시스템",
  description: "AI 제안서 검증 시스템",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full">
      <body className={`${geist.className} min-h-full bg-gray-50`} suppressHydrationWarning>
        <ToastProvider />
        {children}
      </body>
    </html>
  );
}
