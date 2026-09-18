"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

// Windows-style accent color palette (24 colors)
export const ACCENT_COLORS = [
  "#0078D4", // Windows Blue (default)
  "#0099BC", // Teal
  "#00B7C3", // Light Teal
  "#038387", // Dark Teal
  "#00CC6A", // Green
  "#10893E", // Dark Green
  "#7A7574", // Warm Gray
  "#5D5A58", // Dark Gray
  "#68768A", // Steel Blue
  "#515C6B", // Slate
  "#567C73", // Sage
  "#486860", // Dark Sage
  "#498205", // Olive
  "#107C10", // Forest
  "#FF8C00", // Orange
  "#E74856", // Red
  "#C30052", // Rose
  "#BF0077", // Magenta
  "#9B008A", // Purple
  "#881798", // Dark Purple
  "#744DA9", // Violet
  "#8764B8", // Light Violet
  "#0063B1", // Cobalt
  "#2D7D9A", // Ocean
];

const STORAGE_KEY = "accent-color";
const DEFAULT_ACCENT = "#0078D4";

// HEX → RGB 변환
function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace("#", "");
  return {
    r: parseInt(h.substring(0, 2), 16),
    g: parseInt(h.substring(2, 4), 16),
    b: parseInt(h.substring(4, 6), 16),
  };
}

// 액센트 컬러에서 테마 전체 CSS 변수 파생
function applyAccentTheme(hex: string) {
  const { r, g, b } = hexToRgb(hex);
  const root = document.documentElement;
  const isDark = root.classList.contains("dark");

  // 액센트 대비색: 밝은 액센트엔 검은 글자, 어두운 액센트엔 흰 글자
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  root.style.setProperty("--accent-contrast", lum > 160 ? "#000000" : "#FFFFFF");

  root.style.setProperty("--accent-color", hex);

  // 흰색: 순수 흰/회색 톤 (틴트 없음)
  if (hex === "#FFFFFF") {
    if (isDark) {
      root.style.setProperty("--bg-primary", "rgb(18, 18, 18)");
      root.style.setProperty("--bg-secondary", "rgb(30, 30, 30)");
      root.style.setProperty("--bg-tertiary", "rgb(44, 44, 44)");
      root.style.setProperty("--border-color", "rgb(50, 50, 50)");
    } else {
      root.style.setProperty("--bg-primary", "rgb(255, 255, 255)");
      root.style.setProperty("--bg-secondary", "rgb(248, 249, 250)");
      root.style.setProperty("--bg-tertiary", "rgb(233, 236, 239)");
      root.style.setProperty("--border-color", "rgb(233, 236, 239)");
    }
    return;
  }

  // 검은색: 무채색 딥 톤
  if (hex === "#000000") {
    if (isDark) {
      root.style.setProperty("--bg-primary", "rgb(0, 0, 0)");
      root.style.setProperty("--bg-secondary", "rgb(15, 15, 15)");
      root.style.setProperty("--bg-tertiary", "rgb(28, 28, 28)");
      root.style.setProperty("--border-color", "rgb(38, 38, 38)");
    } else {
      root.style.setProperty("--bg-primary", "rgb(245, 245, 245)");
      root.style.setProperty("--bg-secondary", "rgb(235, 235, 235)");
      root.style.setProperty("--bg-tertiary", "rgb(220, 220, 220)");
      root.style.setProperty("--border-color", "rgb(210, 210, 210)");
    }
    return;
  }

  if (isDark) {
    // 다크모드: 어두운 배경에 액센트 틴트 (베이스 14→18→22, 틴트 5→6→7%)
    const darkMix = (c: number, base: number, pct: number) => Math.round(base + c * pct);
    root.style.setProperty("--bg-primary", `rgb(${darkMix(r, 14, 0.05)}, ${darkMix(g, 14, 0.05)}, ${darkMix(b, 14, 0.05)})`);
    root.style.setProperty("--bg-secondary", `rgb(${darkMix(r, 18, 0.06)}, ${darkMix(g, 18, 0.06)}, ${darkMix(b, 18, 0.06)})`);
    root.style.setProperty("--bg-tertiary", `rgb(${darkMix(r, 22, 0.07)}, ${darkMix(g, 22, 0.07)}, ${darkMix(b, 22, 0.07)})`);
    root.style.setProperty("--border-color", `rgb(${darkMix(r, 26, 0.06)}, ${darkMix(g, 26, 0.06)}, ${darkMix(b, 26, 0.06)})`);
  } else {
    // 라이트모드: 밝은 배경에 액센트 틴트 (균일 간격: 4→6→8→7%)
    const mix = (c: number, pct: number) => Math.round(255 - (255 - c) * pct);
    root.style.setProperty("--bg-primary", `rgb(${mix(r, 0.04)}, ${mix(g, 0.04)}, ${mix(b, 0.04)})`);
    root.style.setProperty("--bg-secondary", `rgb(${mix(r, 0.06)}, ${mix(g, 0.06)}, ${mix(b, 0.06)})`);
    root.style.setProperty("--bg-tertiary", `rgb(${mix(r, 0.08)}, ${mix(g, 0.08)}, ${mix(b, 0.08)})`);
    root.style.setProperty("--border-color", `rgb(${mix(r, 0.07)}, ${mix(g, 0.07)}, ${mix(b, 0.07)})`);
  }
}

interface AccentContextType {
  accentColor: string;
  setAccentColor: (color: string) => void;
}

const AccentContext = createContext<AccentContextType>({
  accentColor: DEFAULT_ACCENT,
  setAccentColor: () => {},
});

export function useAccentColor() {
  return useContext(AccentContext);
}

export function AccentProvider({ children }: { children: React.ReactNode }) {
  const [accentColor, setAccentColorState] = useState(DEFAULT_ACCENT);
  const [mounted, setMounted] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setAccentColorState(stored);
      applyAccentTheme(stored);
    }
    setMounted(true);
  }, []);

  // 다크모드 전환 감지 → 액센트 테마 재적용
  useEffect(() => {
    if (!mounted) return;
    const observer = new MutationObserver(() => {
      applyAccentTheme(accentColor);
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, [mounted, accentColor]);

  const setAccentColor = (color: string) => {
    setAccentColorState(color);
    localStorage.setItem(STORAGE_KEY, color);
    applyAccentTheme(color);
  };

  // Set CSS variables on initial render & accent change
  useEffect(() => {
    if (mounted) {
      applyAccentTheme(accentColor);
    }
  }, [accentColor, mounted]);

  return (
    <AccentContext.Provider value={{ accentColor, setAccentColor }}>
      {children}
    </AccentContext.Provider>
  );
}
