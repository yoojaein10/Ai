import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "가야지 | AI 여행 플래너",
  description: "목적지와 날짜만 정하면 AI가 일정부터 동선, 예산, 예약까지 완성하는 여행 플래너",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
