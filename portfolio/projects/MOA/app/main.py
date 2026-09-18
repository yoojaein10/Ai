"""FastAPI 애플리케이션 진입점."""

from fastapi import FastAPI, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import get_settings
from app.routers.health import router as health_router
from app.routers.partners import router as partners_router
from app.routers.account_ledger import router as account_ledger_router
from app.routers.bank_reconcile import router as bank_reconcile_router
from app.routers.tax_bulk import router as tax_bulk_router
from app.routers.external_issue import router as external_issue_router
from app.routers.invoice_pool import router as invoice_pool_router
from app.routers.appraisals import router as appraisals_router
from app.routers.auth import router as auth_router
from app.routers.banje import router as banje_router
from app.routers.bonus import router as bonus_router
from app.routers.bonus_settings import router as bonus_settings_router
from app.routers.bonus_v2 import router as bonus_v2_router
from app.routers.cache_admin import router as cache_admin_router
from app.routers.card_vouchers import router as card_vouchers_router
from app.routers.collection import router as collection_router
from app.routers.data_quality import router as data_quality_router
from app.routers.deposit_yak import router as deposit_yak_router
from app.routers.fee_basis import router as fee_basis_router
from app.routers.reconcile import router as reconcile_router
from app.routers.gamjun_chat import router as gamjun_chat_router
from app.routers.gaprice import router as gaprice_router
from app.routers.my_sales import router as my_sales_router
from app.routers.manual_sales import router as manual_sales_router
from app.routers.payment_sms import router as payment_sms_router
from app.routers.permissions import router as permissions_router
from app.routers.receivables import router as receivables_router
from app.routers.sales_stats import router as sales_stats_router
from app.routers.shinhan_delay import router as shinhan_delay_router
from app.routers.taxinvoice import router as taxinvoice_router
from app.routers.travel_expense import router as travel_expense_router
from app.routers.users import router as users_router
from app.routers.work_report import router as work_report_router
from app.services.permission_preview import (
    PREVIEW_HEADER,
    PREVIEW_QUERY,
    SAFE_METHODS,
    is_loopback_preview_request,
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)
app.include_router(health_router)
app.include_router(partners_router)
app.include_router(account_ledger_router)
app.include_router(bank_reconcile_router)
app.include_router(tax_bulk_router)
app.include_router(external_issue_router)
app.include_router(invoice_pool_router)
app.include_router(appraisals_router)
app.include_router(auth_router)
app.include_router(banje_router)
app.include_router(bonus_router)
app.include_router(bonus_settings_router)
app.include_router(bonus_v2_router)
app.include_router(cache_admin_router)
app.include_router(card_vouchers_router)
app.include_router(collection_router)
app.include_router(data_quality_router)
app.include_router(deposit_yak_router)
app.include_router(fee_basis_router)
app.include_router(reconcile_router)
app.include_router(gaprice_router)
app.include_router(my_sales_router)
app.include_router(manual_sales_router)
app.include_router(payment_sms_router)
app.include_router(permissions_router)
app.include_router(receivables_router)
app.include_router(sales_stats_router)
app.include_router(shinhan_delay_router)
app.include_router(gamjun_chat_router)
app.include_router(taxinvoice_router)
app.include_router(travel_expense_router)
app.include_router(users_router)
app.include_router(work_report_router)


@app.middleware("http")
async def protect_local_permission_preview(request, call_next):
    """로컬 권한 테스트 토큰이 붙은 모든 변경 요청을 라우터 진입 전에 차단한다."""
    preview_token = (
        request.headers.get(PREVIEW_HEADER)
        or request.query_params.get(PREVIEW_QUERY)
    )
    if preview_token:
        if not is_loopback_preview_request(request):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "code": "PREVIEW_LOCAL_ONLY",
                    "message": "권한 테스트는 로컬에서만 사용할 수 있습니다.",
                    "data": None,
                },
            )
        if request.method.upper() not in SAFE_METHODS:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "code": "PREVIEW_READ_ONLY",
                    "message": "권한 테스트에서는 저장·승인·발급·변경할 수 없습니다.",
                    "data": None,
                },
            )
    return await call_next(request)


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DESKTOP_UI_DIR = Path(__file__).parent.parent / "desktop" / "ui"
app.mount("/ui", StaticFiles(directory=DESKTOP_UI_DIR), name="desktop-ui")


def _screen(name: str) -> FileResponse:
    """화면 HTML 은 항상 새로 받게 한다.

    HTML 이 캐시되면 그 안에 적힌 ?v= 도 옛 값이라 새 JS·CSS 를 영영 안 받는다.
    화면마다 손으로 헤더를 달다 보니 13개가 빠져 있었고, 배포해도 옛 화면이 그대로
    보였다 (2026-08-21: 입금발송내역에 새 검색 조건이 안 보인다는 제보. 앞서
    보수기준 점검 화면도 같은 이유였다). 한 곳을 지나가게 해서 빠질 수 없게 한다.
    """
    return FileResponse(
        DESKTOP_UI_DIR / name,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/desktop", include_in_schema=False)
def desktop() -> FileResponse:
    """EXE 와 북마크의 진입점 — 메뉴를 탭으로 띄우는 껍데기다 (2026-08-20).

    종전에는 감정서 LIST 를 바로 줬다. 그 화면은 /desktop/dashboard 로 옮겼고,
    EXE 는 고치지 않아도 켜자마자 탭 화면이 뜬다.
    """
    return _screen("shell.html")


@app.get("/desktop/shell", include_in_schema=False)
def desktop_shell() -> FileResponse:
    """껍데기의 옛 주소 — /desktop 으로 옮기기 전에 쓰던 것이라 그대로 둔다."""
    return _screen("shell.html")


@app.get("/desktop/dashboard", include_in_schema=False)
def desktop_dashboard() -> FileResponse:
    """감정서 LIST — 종전 /desktop 이 주던 화면."""
    return _screen("dashboard.html")


@app.get("/desktop/receivables", include_in_schema=False, response_model=None)
def desktop_receivables(mode: "str | None" = None) -> "FileResponse | RedirectResponse":
    """입금 현황. 미수금 현황과 한 화면(mode 전환)이었다가 분리했다(2026-09-01).

    옛 링크·북마크(?mode=outstanding)는 분리된 화면으로 보낸다 — 캐시된
    context.js 의 사이드 메뉴가 옛 주소를 물고 있어도 동작해야 한다.
    """
    if mode == "outstanding":
        return RedirectResponse("/desktop/outstanding", status_code=307)
    return _screen("receivables.html")


@app.get("/desktop/outstanding", include_in_schema=False)
def desktop_outstanding() -> FileResponse:
    """미수금 현황 — 입금 현황에서 분리(2026-09-01 사용자 요청)."""
    return _screen("outstanding.html")


@app.get("/desktop/shinhan-delay", include_in_schema=False)
def desktop_shinhan_delay() -> FileResponse:
    """신한은행 발송기한 관리 — 회계 MOA 메뉴에 없는 독립 화면 (2026-09-02)."""
    return _screen("shinhan-delay.html")


@app.get("/desktop/allocation", include_in_schema=False)
def desktop_allocation() -> FileResponse:
    # 인쇄 스타일이 HTML 안에 인라인이라, 캐시되면 새 스타일을 영영 안 받는다.
    return _screen("allocation.html")


@app.get("/desktop/sales-stats", include_in_schema=False)
def desktop_sales_stats() -> FileResponse:
    # HTML이 캐시되면 안에 적힌 ?v= 도 옛 값이라 새 JS를 영영 안 받는다.
    return _screen("sales-stats.html")


@app.get("/desktop/gamjun-chat", include_in_schema=False)
def desktop_gamjun_chat() -> FileResponse:
    # HTML이 캐시되면 안에 적힌 ?v= 도 옛 값이라 새 JS를 영영 안 받는다.
    return _screen("gamjun-chat.html")


@app.get("/desktop/my-sales", include_in_schema=False)
def desktop_my_sales() -> FileResponse:
    # HTML이 캐시되면 안에 적힌 ?v= 도 옛 값이라 새 JS를 영영 안 받는다.
    return _screen("my-sales.html")


@app.get("/desktop/permissions", include_in_schema=False)
def desktop_permissions() -> FileResponse:
    return _screen("permissions-preview.html")


@app.get("/desktop/permission-roles", include_in_schema=False)
def desktop_permission_roles() -> FileResponse:
    """권한 묶음 관리 (2026-08-13). 권한 관리 화면과 짝이다 —
    여기서 묶음을 만들고, 저기서 부서·사람에 붙인다."""
    return _screen("permission-roles.html")


@app.get("/desktop/permissions-preview", include_in_schema=False)
def desktop_permissions_preview() -> FileResponse:
    """권한관리 개편안의 로컬 화면. 조직도는 읽기 전용 API로 조회한다."""
    return _screen("permissions-preview.html")


@app.get("/desktop/bonus", include_in_schema=False)
def desktop_bonus() -> FileResponse:
    return _screen("bonus.html")


@app.get("/desktop/bonus-settings", include_in_schema=False)
def desktop_bonus_settings() -> FileResponse:
    """상여 설정(사람·요율·지분) — 상여 화면의 설정 버튼으로 들어오는 딸림 화면 (2026-08-25).

    사이드바에는 안 올린다. 권한은 상여(bonus) 키를 같이 쓴다.
    """
    return _screen("bonus-settings.html")


@app.get("/desktop/bonus-deductions", include_in_schema=False)
def desktop_bonus_deductions() -> FileResponse:
    """상여 공제 대장 — 상여 화면의 '공제 대장' 버튼으로 들어오는 딸림 화면 (2026-08-27).

    사이드바에는 안 올린다. 권한은 상여(bonus) 키를 같이 쓴다.
    """
    return _screen("bonus-deductions.html")


@app.get("/desktop/bonus-legacy", include_in_schema=False)
def desktop_bonus_legacy() -> FileResponse:
    """구 상여 화면(GaPrice 기준) — 9월 지급분 파일럿 동안 대조용으로만 남긴다 (2026-08-27).

    사이드바에는 안 올린다. 권한은 상여(bonus) 키를 같이 쓴다. 파일럿이 끝나면 지운다.
    """
    return _screen("bonus-legacy.html")


@app.get("/desktop/collection", include_in_schema=False)
def desktop_collection() -> FileResponse:
    return _screen("collection.html")


@app.get("/desktop/account-ledger", include_in_schema=False)
def desktop_account_ledger() -> FileResponse:
    """계정별원장 — 지사 계정 원장을 뽑아 메일로 보낸다 (2026-08-21)."""
    return _screen("account-ledger.html")


@app.get("/desktop/ledger-recipients", include_in_schema=False)
def desktop_ledger_recipients() -> FileResponse:
    """지사 메일 주소 관리 — 계정별원장이 나갈 주소를 지사별로 적어 둔다 (2026-08-24).

    사이드바에는 안 올린다. 계정별원장 화면 오른쪽 위 버튼으로 들어가는
    딸림 화면이다(권한 관리 → 일괄권한과 같은 구조).
    """
    return _screen("ledger-recipients.html")


@app.get("/desktop/data-quality", include_in_schema=False)
def desktop_data_quality() -> FileResponse:
    return _screen("data-quality.html")



@app.get("/desktop/fee-basis", include_in_schema=False)
def desktop_fee_basis() -> FileResponse:
    return _screen("fee-basis.html")


@app.get("/desktop/reconcile", include_in_schema=False)
def desktop_reconcile() -> FileResponse:
    return _screen("reconcile.html")


@app.get("/desktop/bank-reconcile", include_in_schema=False)
def desktop_bank_reconcile() -> FileResponse:
    """일계표 대사 — 사이버브랜치 입·출금과 아마란스 보통예금 전표 (2026-08-26)."""
    return _screen("bank-reconcile.html")


@app.get("/desktop/tax-bulk", include_in_schema=False)
def desktop_tax_bulk() -> FileResponse:
    """계산서 등록 — 외부 발행·국세청 매출 자료 엑셀을 발급 원장에 등록 (2026-09-11, 예전 계산서 일괄발급)."""
    return _screen("tax-bulk.html")


@app.get("/desktop/work-report", include_in_schema=False)
def desktop_work_report() -> FileResponse:
    return _screen("work-report.html")


@app.get("/desktop/banje-receivable", include_in_schema=False)
def desktop_banje_receivable() -> FileResponse:
    return _screen("banje-receivable.html")


@app.get("/desktop/banje-advance", include_in_schema=False)
def desktop_banje_advance() -> FileResponse:
    return _screen("banje-advance.html")


@app.get("/desktop/card-vouchers", include_in_schema=False)
def desktop_card_vouchers() -> FileResponse:
    return _screen("card-vouchers.html")


@app.get("/desktop/travel-expense", include_in_schema=False)
def desktop_travel_expense() -> FileResponse:
    """출장비 (2026-09-10) — APWorks 델파이 출장비프로그램 이식."""
    return _screen("travel-expense.html")


@app.get("/desktop/payment-sms", include_in_schema=False)
def desktop_payment_sms() -> FileResponse:
    return _screen("payment-sms.html")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/receivables", include_in_schema=False)
def receivables() -> FileResponse:
    return FileResponse(STATIC_DIR / "receivables.html")


@app.exception_handler(RequestValidationError)
def validation_exception_handler(
    _request: object, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder(
            {
                "success": False,
                "code": "VALIDATION_ERROR",
                "message": "요청값을 확인하세요.",
                "data": exc.errors(),
            }
        ),
    )


@app.exception_handler(HTTPException)
def http_exception_handler(_request: object, exc: HTTPException) -> JSONResponse:
    """권한 계층(app.dependencies)이 dict detail로 올린 오류를 ApiResponse 형태로 변환한다.

    dict가 아닌 detail(기존 라우터의 문자열 detail 등)은 FastAPI 기본 형태를 유지한다.
    """
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "success": False,
                "code": exc.detail.get("code", "HTTP_ERROR"),
                "message": exc.detail.get("message", ""),
                "data": None,
            },
        )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={"detail": exc.detail},
    )
