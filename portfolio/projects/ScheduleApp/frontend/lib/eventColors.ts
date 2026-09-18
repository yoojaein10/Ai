/** 출장/휴가 키워드 기반 색상 — 타임라인·월간·상세 공통 */
export function getTypeColor(title: string): { bg: string; text: string } | null {
  if (title.includes("출장")) return { bg: "#A889A1", text: "#FFFFFF" };
  if (["휴가", "반차", "연차", "병가", "공가"].some((k) => title.includes(k)))
    return { bg: "#FFFF8D", text: "#1A1A1A" };
  return null;
}
