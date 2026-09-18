from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.appointments import router as appointments_router
from app.api.v1.approval import router as approval_router
from app.api.v1.attendance import router as attendance_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.auth import router as auth_router
from app.api.v1.change_requests import router as change_requests_router
from app.api.v1.comp_boss import router as comp_boss_router
from app.api.v1.comp_indicators import router as comp_indicators_router
from app.api.v1.comp_sar import router as comp_sar_router
from app.api.v1.comp_self import router as comp_self_router
from app.api.v1.benefit_events import router as benefit_events_router
from app.api.v1.benefit_health import router as benefit_health_router
from app.api.v1.benefit_items import router as benefit_items_router
from app.api.v1.benefit_overview import router as benefit_overview_router
from app.api.v1.departments import router as departments_router
from app.api.v1.edu_courses import router as edu_courses_router
from app.api.v1.edu_records import router as edu_records_router
from app.api.v1.emp_tabs import router as emp_tabs_router
from app.api.v1.employees import router as employees_router
from app.api.v1.eval_approvers import router as eval_approvers_router
from app.api.v1.eval_calibration import router as eval_calibration_router
from app.api.v1.ai_eval_report import router as ai_eval_report_router
from app.api.v1.eval_comprehensive import router as eval_comprehensive_router
from app.api.v1.eval_objection import router as eval_objection_router
from app.api.v1.eval_rounds import router as eval_rounds_router
from app.api.v1.eval_schedules import router as eval_schedules_router
from app.api.v1.eval_settings import router as eval_settings_router
from app.api.v1.holiday import router as holiday_router
from app.api.v1.leave import router as leave_router
from app.api.v1.leave_request import router as leave_request_router
from app.api.v1.leaves import router as leaves_router
from app.api.v1.me import router as me_router
from app.api.v1.multi_indicators import router as multi_indicators_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.multi_response import router as multi_response_router
from app.api.v1.multi_results import router as multi_results_router
from app.api.v1.perf_final import router as perf_final_router
from app.api.v1.perf_kpis import router as perf_kpis_router
from app.api.v1.perf_midterm import router as perf_midterm_router
from app.api.v1.perf_results import router as perf_results_router
from app.api.v1.perf_targets import router as perf_targets_router
from app.api.v1.stats import router as stats_router
from app.api.v1.travel import router as travel_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(me_router)
api_router.include_router(employees_router)
api_router.include_router(emp_tabs_router)
api_router.include_router(departments_router)
api_router.include_router(appointments_router)
api_router.include_router(change_requests_router)
api_router.include_router(attendance_router)
api_router.include_router(leaves_router)
api_router.include_router(edu_courses_router)
api_router.include_router(edu_records_router)
api_router.include_router(benefit_items_router)
api_router.include_router(benefit_events_router)
api_router.include_router(benefit_health_router)
api_router.include_router(benefit_overview_router)
api_router.include_router(stats_router)
api_router.include_router(eval_rounds_router)
api_router.include_router(eval_schedules_router)
api_router.include_router(eval_approvers_router)
api_router.include_router(eval_calibration_router)
api_router.include_router(eval_settings_router)
api_router.include_router(perf_kpis_router)
api_router.include_router(perf_targets_router)
api_router.include_router(perf_midterm_router)
api_router.include_router(perf_final_router)
api_router.include_router(perf_results_router)
api_router.include_router(comp_indicators_router)
api_router.include_router(comp_self_router)
api_router.include_router(comp_boss_router)
api_router.include_router(comp_sar_router)
api_router.include_router(multi_indicators_router)
api_router.include_router(multi_response_router)
api_router.include_router(multi_results_router)
api_router.include_router(eval_comprehensive_router)
api_router.include_router(ai_eval_report_router)
api_router.include_router(eval_objection_router)
api_router.include_router(admin_router)
api_router.include_router(notifications_router)
api_router.include_router(approval_router)
api_router.include_router(calendar_router)
api_router.include_router(leave_router)
api_router.include_router(holiday_router)
api_router.include_router(leave_request_router)
api_router.include_router(travel_router)
