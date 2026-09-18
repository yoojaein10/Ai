import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Spin } from "antd";
import MainLayout from "./components/MainLayout";
import PlaceholderPage from "./components/PlaceholderPage";
import { useAuthStore } from "./store/auth";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const EmployeeListPage = lazy(() => import("./pages/EmployeeListPage"));
const DepartmentPage = lazy(() => import("./pages/DepartmentPage"));
const AppointmentPage = lazy(() => import("./pages/AppointmentPage"));
const AppointmentStatusPage = lazy(() => import("./pages/AppointmentStatusPage"));
const RosterPage = lazy(() => import("./pages/RosterPage"));
const RecordCardPage = lazy(() => import("./pages/RecordCardPage"));
const DeptHeadPage = lazy(() => import("./pages/DeptHeadPage"));
const MyInfoPage = lazy(() => import("./pages/MyInfoPage"));
const CertificatePage = lazy(() => import("./pages/CertificatePage"));
const ApprovalPage = lazy(() => import("./pages/ApprovalPage"));
const AttendanceDailyPage = lazy(() => import("./pages/AttendanceDailyPage"));
const AttendanceDetailPage = lazy(() => import("./pages/AttendanceDetailPage"));
const AttendanceSummaryPage = lazy(() => import("./pages/AttendanceSummaryPage"));
const LeavePage = lazy(() => import("./pages/LeavePage"));
const MyLeavePage = lazy(() => import("./pages/leave/MyLeavePage"));
const AdminLeavePage = lazy(() => import("./pages/leave/AdminLeavePage"));
const LeaveRulePage = lazy(() => import("./pages/leave/LeaveRulePage"));
const LeaveRequestPage = lazy(() => import("./pages/leave/LeaveRequestPage"));
const MyLeaveRequestsPage = lazy(() => import("./pages/leave/MyLeaveRequestsPage"));
const TeamLeaveRequestsPage = lazy(() => import("./pages/leave/TeamLeaveRequestsPage"));
const HolidayMgmtPage = lazy(() => import("./pages/leave/HolidayMgmtPage"));
const EduCoursesPage = lazy(() => import("./pages/EduCoursesPage"));
const EduRecordsPage = lazy(() => import("./pages/EduRecordsPage"));
const BenefitOverviewPage = lazy(() => import("./pages/BenefitOverviewPage"));
const BenefitEventsPage = lazy(() => import("./pages/BenefitEventsPage"));
const BenefitHealthPage = lazy(() => import("./pages/BenefitHealthPage"));
const StatWorkforcePage = lazy(() => import("./pages/StatWorkforcePage"));
const StatAttendancePage = lazy(() => import("./pages/StatAttendancePage"));
const StatEducationPage = lazy(() => import("./pages/StatEducationPage"));
const AdminUsersPage = lazy(() => import("./pages/AdminUsersPage"));
const AdminRolesPage = lazy(() => import("./pages/AdminRolesPage"));
const AdminCodesPage = lazy(() => import("./pages/AdminCodesPage"));
const AdminSettingsPage = lazy(() => import("./pages/AdminSettingsPage"));
const EvalRoundPage = lazy(() => import("./pages/EvalRoundPage"));
const EvalSchedulePage = lazy(() => import("./pages/EvalSchedulePage"));
const EvalApproverPage = lazy(() => import("./pages/EvalApproverPage"));
const EvalCalibrationPage = lazy(() => import("./pages/EvalCalibrationPage"));
const EvalSettingPage = lazy(() => import("./pages/EvalSettingPage"));
const PerfMyDashboardPage = lazy(() => import("./pages/PerfMyDashboardPage"));
const PerfTargetSettingPage = lazy(() => import("./pages/PerfTargetSettingPage"));
const PerfMidtermPage = lazy(() => import("./pages/PerfMidtermPage"));
const PerfFinalPage = lazy(() => import("./pages/PerfFinalPage"));
const PerfApprovalInboxPage = lazy(() => import("./pages/PerfApprovalInboxPage"));
const PerfTeamStatusPage = lazy(() => import("./pages/PerfTeamStatusPage"));
const CompSelfPage = lazy(() => import("./pages/CompSelfPage"));
const CompBossPage = lazy(() => import("./pages/CompBossPage"));
const CompSarPage = lazy(() => import("./pages/CompSarPage"));
const MultiEvalPage = lazy(() => import("./pages/MultiEvalPage"));
const MultiResultPage = lazy(() => import("./pages/MultiResultPage"));
const MultiStatusPage = lazy(() => import("./pages/MultiStatusPage"));
const EvalComprehensiveListPage = lazy(() => import("./pages/EvalComprehensiveListPage"));
const EvalGradeAdjustmentPage = lazy(() => import("./pages/EvalGradeAdjustmentPage"));
const EvalObjectionListPage = lazy(() => import("./pages/EvalObjectionListPage"));
const EvalMyResultPage = lazy(() => import("./pages/EvalMyResultPage"));
const ApprovalInboxPage = lazy(() => import("./pages/approval/Inbox"));
const ApprovalDraftsPage = lazy(() => import("./pages/approval/Drafts"));
const ApprovalDocDetailPage = lazy(() => import("./pages/approval/DocDetail"));
const ApprovalDocTypeMgmtPage = lazy(() => import("./pages/approval/DocTypeMgmt"));
const ApprovalLineTemplateMgmtPage = lazy(() => import("./pages/approval/LineTemplateMgmt"));
const CompanyCalendarPage = lazy(() => import("./pages/calendar/CompanyCalendar"));
const MyCalendarPage = lazy(() => import("./pages/calendar/MyCalendar"));
const DeptCalendarPage = lazy(() => import("./pages/calendar/DeptCalendar"));
const TravelOrderPage = lazy(() => import("./pages/travel/TravelOrderPage"));
const MyTravelOrdersPage = lazy(() => import("./pages/travel/MyTravelOrdersPage"));
const TeamTravelOrdersPage = lazy(() => import("./pages/travel/TeamTravelOrdersPage"));
const TravelReportPage = lazy(() => import("./pages/travel/TravelReportPage"));
const SalaryPage = lazy(() => import("./pages/SalaryPage"));
const SalaryAdminPage = lazy(() => import("./pages/SalaryAdminPage"));

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.accessToken);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function PageFallback() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: 64 }}>
      <Spin size="large" />
    </div>
  );
}

const placeholderRoutes: { path: string; title: string }[] = [
  { path: "/att/overtime", title: "초과근무" },
  { path: "/doc/inbox", title: "수신함" },
  { path: "/doc/outbox", title: "발신함" },
  { path: "/doc/approval", title: "결재함" },
];

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <PrivateRoute>
              <MainLayout>
                <Suspense fallback={<PageFallback />}>
                  <Routes>
                    <Route path="/" element={<Navigate to="/hr/employees" replace />} />
                    <Route path="/hr/my-info" element={<MyInfoPage />} />
                    <Route path="/hr/certificates" element={<CertificatePage />} />
                    <Route path="/hr/approval" element={<ApprovalPage />} />
                    <Route path="/hr/employees" element={<EmployeeListPage />} />
                    <Route path="/hr/departments" element={<DepartmentPage />} />
                    <Route path="/hr/dept-heads" element={<DeptHeadPage />} />
                    <Route path="/hr/appointments" element={<AppointmentPage />} />
                    <Route path="/hr/appointments/status" element={<AppointmentStatusPage />} />
                    <Route path="/hr/roster" element={<RosterPage />} />
                    <Route path="/hr/record-card" element={<RecordCardPage />} />
                    <Route path="/att/daily" element={<AttendanceDailyPage />} />
                    <Route path="/att/summary" element={<AttendanceSummaryPage />} />
                    <Route path="/att/detail" element={<AttendanceDetailPage />} />
                    <Route path="/att/leave" element={<LeavePage />} />
                    <Route path="/att/leave/me" element={<MyLeavePage />} />
                    <Route path="/att/leave/admin" element={<AdminLeavePage />} />
                    <Route path="/att/leave/rules" element={<LeaveRulePage />} />
                    <Route path="/att/leave/request" element={<LeaveRequestPage />} />
                    <Route path="/att/leave/my-requests" element={<MyLeaveRequestsPage />} />
                    <Route path="/att/leave/team-requests" element={<TeamLeaveRequestsPage />} />
                    <Route path="/att/leave/holidays" element={<HolidayMgmtPage />} />
                    <Route path="/edu/courses" element={<EduCoursesPage />} />
                    <Route path="/edu/records" element={<EduRecordsPage />} />
                    <Route path="/benefit/overview" element={<BenefitOverviewPage />} />
                    <Route path="/benefit/events" element={<BenefitEventsPage />} />
                    <Route path="/benefit/health" element={<BenefitHealthPage />} />
                    <Route path="/stat/workforce" element={<StatWorkforcePage />} />
                    <Route path="/stat/attendance" element={<StatAttendancePage />} />
                    <Route path="/stat/education" element={<StatEducationPage />} />
                    <Route path="/eval/rounds" element={<EvalRoundPage />} />
                    <Route path="/eval/schedules" element={<EvalSchedulePage />} />
                    <Route path="/eval/approvers" element={<EvalApproverPage />} />
                    <Route path="/eval/calibration" element={<EvalCalibrationPage />} />
                    <Route path="/eval/settings" element={<EvalSettingPage />} />
                    <Route path="/eval/perf/dashboard" element={<PerfMyDashboardPage />} />
                    <Route path="/eval/perf/target" element={<PerfTargetSettingPage />} />
                    <Route path="/eval/perf/midterm" element={<PerfMidtermPage />} />
                    <Route path="/eval/perf/final" element={<PerfFinalPage />} />
                    <Route path="/eval/perf/approval" element={<PerfApprovalInboxPage />} />
                    <Route path="/eval/perf/team" element={<PerfTeamStatusPage />} />
                    <Route path="/eval/comp/self" element={<CompSelfPage />} />
                    <Route path="/eval/comp/boss" element={<CompBossPage />} />
                    <Route path="/eval/comp/sar" element={<CompSarPage />} />
                    <Route path="/eval/multi/input" element={<MultiEvalPage />} />
                    <Route path="/eval/multi/result" element={<MultiResultPage />} />
                    <Route path="/eval/multi/status" element={<MultiStatusPage />} />
                    <Route path="/eval/comprehensive" element={<EvalComprehensiveListPage />} />
                    <Route path="/eval/comprehensive/adjust" element={<EvalGradeAdjustmentPage />} />
                    <Route path="/eval/objection" element={<EvalObjectionListPage />} />
                    <Route path="/eval/my-result" element={<EvalMyResultPage />} />
                    <Route path="/approval/inbox" element={<ApprovalInboxPage />} />
                    <Route path="/approval/drafts" element={<ApprovalDraftsPage />} />
                    <Route path="/approval/docs/:docId" element={<ApprovalDocDetailPage />} />
                    <Route path="/approval/admin/doc-types" element={<ApprovalDocTypeMgmtPage />} />
                    <Route path="/approval/admin/line-templates" element={<ApprovalLineTemplateMgmtPage />} />
                    <Route path="/calendar/company" element={<CompanyCalendarPage />} />
                    <Route path="/calendar/me" element={<MyCalendarPage />} />
                    <Route path="/calendar/dept" element={<DeptCalendarPage />} />
                    <Route path="/travel/new" element={<TravelOrderPage />} />
                    <Route path="/travel/my" element={<MyTravelOrdersPage />} />
                    <Route path="/travel/team" element={<TeamTravelOrdersPage />} />
                    <Route path="/travel/:docId/report" element={<TravelReportPage />} />
                    <Route path="/salary" element={<SalaryPage />} />
                    <Route path="/admin/salary-access" element={<SalaryAdminPage />} />
                    <Route path="/admin/users" element={<AdminUsersPage />} />
                    <Route path="/admin/roles" element={<AdminRolesPage />} />
                    <Route path="/admin/codes" element={<AdminCodesPage />} />
                    <Route path="/admin/settings" element={<AdminSettingsPage />} />
                    {placeholderRoutes.map(({ path, title }) => (
                      <Route
                        key={path}
                        path={path}
                        element={<PlaceholderPage title={title} />}
                      />
                    ))}
                  </Routes>
                </Suspense>
              </MainLayout>
            </PrivateRoute>
          }
        />
      </Routes>
    </Suspense>
  );
}
