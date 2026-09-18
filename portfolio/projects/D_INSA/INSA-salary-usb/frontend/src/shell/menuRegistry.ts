/*
 * Single source of truth for application navigation.
 * Consumed by SideNav (tree form) and CommandPalette (flat form).
 * Keep in sync with the routes registered in App.tsx.
 */

export type GnbKey =
  | "인사"
  | "근태"
  | "교육"
  | "복리후생"
  | "인사평가"
  | "전자결재"
  | "캘린더"
  | "문서함"
  | "통계"
  | "관리";

export const GNB_ORDER: GnbKey[] = [
  "인사",
  "근태",
  "교육",
  "복리후생",
  "인사평가",
  "전자결재",
  "캘린더",
  "문서함",
  "통계",
  "관리",
];

export type MenuGroup = {
  key: string;
  label: string;
  items: MenuLeaf[];
};

export type MenuLeaf = {
  path: string;
  label: string;
  /** Icon name from @ant-design/icons; resolved lazily in components to avoid bundling. */
  icon?: string;
  /** Extra search tokens for the command palette (synonyms, English, abbreviations). */
  keywords?: string[];
  /** Roles allowed to see this menu item. */
  roles?: string[];
};

export type DomainMenu = {
  gnb: GnbKey;
  defaultPath: string;
  groups: MenuGroup[];
};

export const MENU: Record<GnbKey, DomainMenu> = {
  인사: {
    gnb: "인사",
    defaultPath: "/hr/employees",
    groups: [
      {
        key: "my-hr",
        label: "나의 인사정보",
        items: [
          { path: "/hr/my-info", label: "인사정보", icon: "User", keywords: ["my", "profile"] },
          { path: "/hr/certificates", label: "증명서발급", icon: "File", keywords: ["certificate"] },
        ],
      },
      {
        key: "hr-mgmt",
        label: "인사관리",
        items: [
          { path: "/hr/employees", label: "인사정보관리", icon: "Team", keywords: ["employee", "직원"] },
          { path: "/hr/approval", label: "변경승인", icon: "File", keywords: ["approval", "승인"] },
        ],
      },
      {
        key: "salary",
        label: "연봉관리",
        items: [
          {
            path: "/salary",
            label: "연봉관리",
            icon: "Solution",
            keywords: ["salary", "연봉", "급여", "vault"],
            roles: ["SYSTEM_ADMIN", "HR_ADMIN"],
          },
        ],
      },
      {
        key: "appt-mgmt",
        label: "발령관리",
        items: [
          { path: "/hr/appointments", label: "인사발령", icon: "Swap", keywords: ["appointment"] },
          { path: "/hr/appointments/status", label: "발령현황", icon: "File" },
        ],
      },
      {
        key: "dept-mgmt",
        label: "부서관리",
        items: [
          { path: "/hr/departments", label: "부서관리", icon: "Team", keywords: ["department"] },
          { path: "/hr/dept-heads", label: "부서장관리", icon: "User" },
        ],
      },
      {
        key: "search",
        label: "임직원조회",
        items: [
          { path: "/hr/roster", label: "재직자명부", icon: "Team", keywords: ["roster"] },
          { path: "/hr/record-card", label: "인사기록카드", icon: "File", keywords: ["record"] },
        ],
      },
    ],
  },
  근태: {
    gnb: "근태",
    defaultPath: "/att/daily",
    groups: [
      {
        key: "att",
        label: "근태관리",
        items: [
          { path: "/att/daily", label: "출퇴근현황", icon: "Clock", keywords: ["attendance"] },
          { path: "/att/detail", label: "개인별상세", icon: "User" },
          { path: "/att/summary", label: "근태집계", icon: "Chart" },
          { path: "/att/leave", label: "휴가관리", icon: "File", keywords: ["leave", "휴가"] },
          { path: "/att/overtime", label: "초과근무", icon: "Clock", keywords: ["overtime"] },
        ],
      },
      {
        key: "leave",
        label: "연차관리",
        items: [
          { path: "/att/leave/me", label: "내 연차", icon: "User", keywords: ["leave", "my", "연차"] },
          { path: "/att/leave/request", label: "휴가 신청", icon: "File", keywords: ["leave", "request", "신청"] },
          { path: "/att/leave/my-requests", label: "내 휴가 신청 내역", icon: "File", keywords: ["leave", "my requests", "내역"] },
          { path: "/att/leave/team-requests", label: "팀 휴가 현황", icon: "Team", keywords: ["leave", "team", "팀"] },
          { path: "/att/leave/admin", label: "연차 잔여 관리", icon: "Team", keywords: ["leave", "balance", "admin"] },
          { path: "/att/leave/rules", label: "연차 규칙 · 운영", icon: "Setting", keywords: ["leave", "rule", "accrual"] },
          { path: "/att/leave/holidays", label: "공휴일 관리", icon: "Calendar", keywords: ["holiday", "공휴일"] },
        ],
      },
    ],
  },
  교육: {
    gnb: "교육",
    defaultPath: "/edu/courses",
    groups: [
      {
        key: "edu",
        label: "교육관리",
        items: [
          { path: "/edu/courses", label: "교육과정", icon: "Read", keywords: ["course"] },
          { path: "/edu/records", label: "교육이수현황", icon: "File" },
        ],
      },
    ],
  },
  복리후생: {
    gnb: "복리후생",
    defaultPath: "/benefit/overview",
    groups: [
      {
        key: "ben",
        label: "복리후생",
        items: [
          { path: "/benefit/overview", label: "복리후생현황", icon: "Heart" },
          { path: "/benefit/events", label: "경조사관리", icon: "Heart" },
          { path: "/benefit/health", label: "건강검진", icon: "Heart", keywords: ["health"] },
        ],
      },
    ],
  },
  인사평가: {
    gnb: "인사평가",
    defaultPath: "/eval/rounds",
    groups: [
      {
        key: "eval-setup",
        label: "평가 설정",
        items: [
          { path: "/eval/rounds", label: "평가 회차", icon: "Solution", keywords: ["round"] },
          { path: "/eval/schedules", label: "평가 일정", icon: "Clock" },
          { path: "/eval/approvers", label: "평가자 매핑", icon: "Team" },
          { path: "/eval/calibration", label: "보정집단", icon: "Team", keywords: ["calibration"] },
          { path: "/eval/settings", label: "반영비율/등급", icon: "Setting" },
        ],
      },
      {
        key: "eval-perf",
        label: "성과평가",
        items: [
          { path: "/eval/perf/dashboard", label: "내 평가 현황", icon: "Chart" },
          { path: "/eval/perf/target", label: "목표과제 작성", icon: "File", keywords: ["KPI", "target"] },
          { path: "/eval/perf/midterm", label: "중간점검", icon: "Clock" },
          { path: "/eval/perf/final", label: "기말실적", icon: "File" },
          { path: "/eval/perf/approval", label: "승인 대기", icon: "Inbox" },
          { path: "/eval/perf/team", label: "부서별 현황", icon: "Team" },
        ],
      },
      {
        key: "eval-comp",
        label: "역량평가",
        items: [
          { path: "/eval/comp/self", label: "본인평가", icon: "User", keywords: ["self"] },
          { path: "/eval/comp/boss", label: "상사평가", icon: "Solution" },
          { path: "/eval/comp/sar", label: "SAR 관찰기록", icon: "File", keywords: ["SAR"] },
        ],
      },
      {
        key: "eval-multi",
        label: "다면평가",
        items: [
          { path: "/eval/multi/input", label: "다면평가 입력", icon: "File" },
          { path: "/eval/multi/result", label: "내 다면평가 결과", icon: "Chart" },
          { path: "/eval/multi/status", label: "제출 현황", icon: "Chart" },
        ],
      },
      {
        key: "eval-comp-final",
        label: "종합평가",
        items: [
          { path: "/eval/comprehensive", label: "종합평가 조회", icon: "Chart" },
          { path: "/eval/comprehensive/adjust", label: "등급 조정", icon: "Setting" },
          { path: "/eval/objection", label: "이의신청", icon: "File", keywords: ["objection"] },
          { path: "/eval/my-result", label: "내 종합 결과", icon: "Solution" },
        ],
      },
    ],
  },
  전자결재: {
    gnb: "전자결재",
    defaultPath: "/approval/inbox",
    groups: [
      {
        key: "approval-my",
        label: "나의 결재",
        items: [
          { path: "/approval/inbox", label: "결재함", icon: "Inbox", keywords: ["approval", "inbox", "결재"] },
          { path: "/approval/drafts", label: "기안함", icon: "File", keywords: ["draft", "기안"] },
        ],
      },
      {
        key: "travel",
        label: "출장",
        items: [
          { path: "/travel/new", label: "출장 기안", icon: "File", keywords: ["travel", "출장", "기안"] },
          { path: "/travel/my", label: "내 출장", icon: "User", keywords: ["travel", "my", "출장"] },
          { path: "/travel/team", label: "팀 출장 현황", icon: "Team", keywords: ["travel", "team", "팀"] },
        ],
      },
      {
        key: "approval-admin",
        label: "관리",
        items: [
          { path: "/approval/admin/doc-types", label: "문서 타입", icon: "Setting", keywords: ["doc type", "문서타입"] },
          { path: "/approval/admin/line-templates", label: "결재선 템플릿", icon: "Team", keywords: ["line", "template", "결재선"] },
        ],
      },
    ],
  },
  캘린더: {
    gnb: "캘린더",
    defaultPath: "/calendar/company",
    groups: [
      {
        key: "cal",
        label: "캘린더",
        items: [
          { path: "/calendar/company", label: "회사 캘린더", icon: "Calendar", keywords: ["calendar", "company", "회사"] },
          { path: "/calendar/me", label: "내 캘린더", icon: "User", keywords: ["my", "me", "내"] },
          { path: "/calendar/dept", label: "부서 캘린더", icon: "Team", keywords: ["dept", "부서"] },
        ],
      },
    ],
  },
  문서함: {
    gnb: "문서함",
    defaultPath: "/doc/inbox",
    groups: [
      {
        key: "doc",
        label: "문서함",
        items: [
          { path: "/doc/inbox", label: "수신함", icon: "Inbox" },
          { path: "/doc/outbox", label: "발신함", icon: "Inbox" },
          { path: "/doc/approval", label: "결재함", icon: "File" },
        ],
      },
    ],
  },
  통계: {
    gnb: "통계",
    defaultPath: "/stat/workforce",
    groups: [
      {
        key: "stat",
        label: "통계",
        items: [
          { path: "/stat/workforce", label: "인력현황", icon: "Chart", keywords: ["workforce"] },
          { path: "/stat/attendance", label: "근태통계", icon: "Chart" },
          { path: "/stat/education", label: "교육통계", icon: "Chart" },
        ],
      },
    ],
  },
  관리: {
    gnb: "관리",
    defaultPath: "/admin/users",
    groups: [
      {
        key: "admin",
        label: "시스템관리",
        items: [
          { path: "/admin/users", label: "사용자관리", icon: "User" },
          { path: "/admin/roles", label: "권한관리", icon: "Setting" },
          { path: "/admin/codes", label: "코드관리", icon: "Setting" },
          { path: "/admin/settings", label: "시스템설정", icon: "Setting" },
          {
            path: "/admin/salary-access",
            label: "연봉접근관리",
            icon: "Setting",
            keywords: ["salary", "연봉", "ip", "감사"],
            roles: ["SYSTEM_ADMIN"],
          },
        ],
      },
    ],
  },
};

const PATH_PREFIX_TO_GNB: Array<[string, GnbKey]> = [
  ["/hr", "인사"],
  ["/att", "근태"],
  ["/edu", "교육"],
  ["/benefit", "복리후생"],
  ["/eval", "인사평가"],
  ["/approval", "전자결재"],
  ["/travel", "전자결재"],
  ["/calendar", "캘린더"],
  ["/doc", "문서함"],
  ["/stat", "통계"],
  ["/salary", "인사"],
  ["/admin", "관리"],
];

export function resolveGnbFromPath(pathname: string): GnbKey {
  const match = PATH_PREFIX_TO_GNB.find(([prefix]) => pathname.startsWith(prefix));
  return match ? match[1] : "인사";
}

export type FlatMenuEntry = MenuLeaf & {
  gnb: GnbKey;
  groupLabel: string;
  breadcrumb: string;
};

export function flattenMenu(): FlatMenuEntry[] {
  const result: FlatMenuEntry[] = [];
  for (const gnb of GNB_ORDER) {
    for (const group of MENU[gnb].groups) {
      for (const item of group.items) {
        result.push({
          ...item,
          gnb,
          groupLabel: group.label,
          breadcrumb: `${gnb} · ${group.label}`,
        });
      }
    }
  }
  return result;
}

export function findEntryByPath(pathname: string): FlatMenuEntry | undefined {
  return flattenMenu().find((e) => e.path === pathname);
}
