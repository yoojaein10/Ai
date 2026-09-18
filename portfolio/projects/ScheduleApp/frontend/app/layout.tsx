import type { Metadata } from "next";
import { ThemeProvider } from "@/components/theme-provider";
import { AccentProvider } from "@/components/accent-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Schedule Calendar",
  description: "KakaoTalk-style Schedule Calendar Application",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body className="bg-bg-primary text-txt-primary antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem={true}
          storageKey="theme"
        >
          <AccentProvider>
            {children}
          </AccentProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
