import type { CSSProperties } from "react";

function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

type AvatarProps = {
  name: string;
  size?: number;
  ariaLabel?: string;
};

export function Avatar({ name, size = 28, ariaLabel }: AvatarProps) {
  const trimmed = name.trim();
  const initial = trimmed.slice(0, 1) || "·";
  const paletteIndex = trimmed ? (hashString(trimmed) % 5) + 1 : 1;

  const style: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: size,
    height: size,
    borderRadius: "50%",
    background: `var(--avatar-${paletteIndex})`,
    color: "#fff",
    fontFamily: "var(--font-display)",
    fontSize: Math.round(size * 0.46),
    fontWeight: 500,
    lineHeight: 1,
    userSelect: "none",
    flexShrink: 0,
  };

  return (
    <span style={style} aria-label={ariaLabel ?? (trimmed || undefined)}>
      {initial}
    </span>
  );
}
