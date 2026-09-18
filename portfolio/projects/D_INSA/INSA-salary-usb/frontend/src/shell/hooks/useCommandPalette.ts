import { useEffect, useMemo, useState } from "react";

const RECENT_STORAGE_KEY = "insa.palette.recent";
const MAX_RECENT = 8;

export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  const isMac = useMemo(
    () =>
      typeof navigator !== "undefined" &&
      /mac|iphone|ipad|ipod/i.test(navigator.platform),
    []
  );
  const shortcutLabel = isMac ? "⌘K" : "Ctrl K";

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isShortcut = isMac ? e.metaKey : e.ctrlKey;
      if (isShortcut && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
        return;
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isMac, open]);

  return { open, setOpen, isMac, shortcutLabel };
}

export function loadRecentPaths(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((p) => typeof p === "string") : [];
  } catch {
    return [];
  }
}

export function pushRecentPath(path: string) {
  try {
    const list = loadRecentPaths().filter((p) => p !== path);
    list.unshift(path);
    localStorage.setItem(
      RECENT_STORAGE_KEY,
      JSON.stringify(list.slice(0, MAX_RECENT))
    );
  } catch {
    // ignore storage failures
  }
}
