import { CalendarEvent } from "./types";

export const VACATION_KEYWORDS = ["휴가", "반차", "연차", "병가", "공가"];

// 그룹 순서: 0=전체, 1=개인, 2=휴가, 3=부서
export function getEventGroupOrder(event: CalendarEvent): number {
  if (event.source === "iw_schedule") {
    return VACATION_KEYWORDS.some((kw) => (event.title ?? "").includes(kw)) ? 2 : 3;
  }
  switch (event.visibility) {
    case "company":  return 0;
    case "personal": return 1;
    default:         return 3;
  }
}

export function sortCalendarEvents(events: CalendarEvent[]): CalendarEvent[] {
  return [...events].sort((a, b) => {
    // 1. 그룹
    const gd = getEventGroupOrder(a) - getEventGroupOrder(b);
    if (gd !== 0) return gd;

    // 2. 종일 먼저
    const ad = (a.is_all_day ? 0 : 1) - (b.is_all_day ? 0 : 1);
    if (ad !== 0) return ad;

    // 3. 시작시간 빠른 순
    const td = new Date(a.start_dt).getTime() - new Date(b.start_dt).getTime();
    if (td !== 0) return td;

    // 4. 직원명 가나다순 (creator_name 우선, 없으면 빈 문자열)
    const na = a.creator_name ?? "";
    const nb = b.creator_name ?? "";
    const nd = na.localeCompare(nb, "ko");
    if (nd !== 0) return nd;

    // 5. 제목 가나다순
    return (a.title ?? "").localeCompare(b.title ?? "", "ko");
  });
}
