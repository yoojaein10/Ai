"""환경변수 기반 애플리케이션 설정."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`.env`와 환경변수에서 읽는 설정.

    비밀값은 로그나 repr에 평문으로 노출되지 않도록 SecretStr로 보관한다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "A10-Bridge"
    app_version: str = "0.1.0"

    # /docs·/redoc·/openapi.json 을 열지 여부. 운영은 꺼 둔다 — 켜 두면 전체 API
    # 목록과 파라미터가 그대로 보여서, 주소를 아는 사람에게 지도를 쥐여 주는 셈이다.
    # 개발할 때는 .env 에 ENABLE_API_DOCS=true 를 두고 로컬에서만 켠다.
    enable_api_docs: bool = False

    # 로그인 증표(app/services/auth_token.py) 서명 키. 비우면 임시 키를 만들어
    # 쓰는데, 그러면 서버를 다시 띄울 때마다 모두 다시 로그인해야 한다.
    auth_token_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))
    # 권한을 **바꾸는** API 에 증표를 요구할지. 종전에는 헤더의 숫자 하나만 믿었다.
    # 기본은 켬 — 이걸 끄면 주소를 아는 사람이 전사 권한을 갈아치울 수 있다.
    # EXE 런처는 조회만 하므로 이 스위치의 영향을 받지 않는다.
    auth_require_token_for_writes: bool = True

    a10_base_url: str = ""
    a10_caller_name: str = ""
    a10_access_token: SecretStr = Field(default_factory=lambda: SecretStr(""))
    a10_hash_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    a10_group_seq: str = ""

    mssql_server: str = ""
    mssql_port: int = 1433
    mssql_db: str = ""
    mssql_source_db: str = "apworksdw"
    mssql_user: str = ""
    mssql_password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    mssql_driver: str = "ODBC Driver 18 for SQL Server"
    mssql_encrypt: str = "yes"
    mssql_trust_server_certificate: str = "no"

    # 아래 둘은 같은 DB(gamjundw)를 가리키지만 접속 경로가 다르다.
    # 보수기준 점검(fee_basis)은 MSSQL_USER/PASSWORD를 재사용하고,
    # 보수기준 검토(fee_review)는 별도 자격증명을 환경변수·외부 파일에서 읽는다.
    # 언젠가 한 경로로 합치는 게 맞다(docs/FEE_REVIEW_JUN_EXPANDED_SEARCH.md 참조).

    # 감정서 PDF 파싱 DB(LLM 서비스 산출물). 계정은 MSSQL_USER/PASSWORD 재사용.
    gamjun_parse_server: str = '192.0.2.10'
    gamjun_parse_db: str = "gamjundw"

    # 감정서 조회 챗봇의 필터 추출·요약 LLM. 키는 .env 에만 둔다(커밋 금지).
    gemini_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))

    # JUN 감정서 원문 근거 조회. 자격증명은 환경변수나 외부 파일에만 둔다.
    # 개발 PC에서는 비어 있으면 D:\JunPdf\jun_sql_connection.txt를 우선 읽고,
    # 호환용 APW_MASTEREX_*.txt를 후순위로 읽기 전용 탐색한다.
    jun_sql_connection_string: SecretStr = Field(default_factory=lambda: SecretStr(""))
    jun_sql_connection_file: str = ""
    jun_sql_database: str = "gamjundw"

    bridge_host: str = "0.0.0.0"
    bridge_port: int = 8010
    log_level: str = "INFO"
    # 운영 기본값은 DB 저장 실패 시 요청도 실패시킨다. 로컬 개발에서만 true.
    fee_review_allow_memory_fallback: bool = False

    # 팝빌(링크허브) 전자세금계산서. 발급까지 MOA가 하면 TAMS 부가세.DB 의존이 사라진다.
    # is_test=True면 팝빌 테스트 서버로만 발행(국세청·거래처 미전송).
    popbill_link_id: str = ""
    popbill_secret_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    popbill_corp_num: str = ""  # 공급자(대화감정평가) 사업자번호, '-' 없이 10자리
    popbill_user_id: str = ""   # 팝빌 회원 아이디
    popbill_is_test: bool = True
    # 공급자(우리 회사) 세금계산서 표기 정보 — 팝빌이 대표자명 등을 필수로 요구한다.
    popbill_supplier_name: str = "대화감정평가법인"
    popbill_supplier_ceo: str = ""
    popbill_supplier_addr: str = ""
    popbill_supplier_biztype: str = "서비스"
    popbill_supplier_bizclass: str = "감정평가"
    popbill_supplier_tel: str = ""
    popbill_supplier_email: str = ""
    # 팩스 발신번호 — 팝빌에 사전 등록된 번호만 발신 가능(운영 등록: 02-525-4555).
    popbill_fax_sender: str = "025254555"

    # 메일 발송(SMTP) — 계정별원장을 지사에 보내는 용도 (2026-08-21).
    # 비어 있으면 발송 기능이 꺼진다(fail-closed). 비밀번호는 .env 에만 둔다.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    smtp_from: str = ""             # 보내는 사람 (비면 smtp_user)
    smtp_from_name: str = "대화감정평가법인"
    smtp_use_tls: bool = True       # 587=STARTTLS, 465=SSL 은 smtp_use_ssl
    smtp_use_ssl: bool = False
    # 테스트 수신자 — 이 값이 있으면 **누구에게 보내든 여기로만** 간다.
    # 실제 지사 주소가 정리되기 전까지 안전장치다 (2026-08-21 사용자 지시).
    ledger_mail_test_to: str = ""

    # 카드내역 원천 DB(Branch, 카드사 API 수집분) — 카드전표 '카드내역 불러오기'용.
    # 읽기 전용 조회만 한다. 비어 있으면 기능이 비활성화된다(fail-closed).
    card_source_server: str = ""
    card_source_db: str = "Branch"
    card_source_user: str = ""
    card_source_password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    # 카드내역 원천(CB2_APPR)에는 지사 카드도 함께 들어온다. 카드전표는 본사 전용이라
    # 본사 사업자번호(Sa_No)로 걸러 받는다 — 2026-08-20 실측: 8/1~8/19 1,043건 중
    # 195건(19%)이 울산지사·타 사업장 카드였다. 비워 두면 거르지 않는다.
    card_source_hq_reg_no: str = "2148746436"   # (주)대화감정평가법인 본사

    # 협회(KAPA) 업무실적 REST 전송. LAWREP 제출은 USERID/PASSWD + 날짜토큰(AK)로 인증한다.
    # (hex API KEY는 webrest.kapanet.or.kr 계열 API용이며 LAWREP 제출엔 쓰지 않는다.)
    kapa_lawrep_base_url: str = "https://m.kapanet.or.kr"
    kapa_lawrep_user: str = ""
    kapa_lawrep_pw: SecretStr = Field(default_factory=lambda: SecretStr(""))
    kapa_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))  # webrest 계열용

    # 입금내역 알림톡 (비즈뿌리오 DB 에이전트 — 같은 서버 KakaoMMs.dbo.BIZ_MSG에 INSERT)
    bizppurio_db: str = "KakaoMMs"
    bizppurio_sender_key: str = ""       # 발신프로필 키 (대화감정평가법인)
    bizppurio_template_code: str = ""    # 입금내역알림 템플릿 코드
    bizppurio_send_phone: str = ""       # 발신번호
    # 테스트 번호가 설정돼 있으면 모든 알림톡을 이 번호로 보낸다 (실수신자 발송 방지)
    payment_alert_test_phone: str = ""
    # 배치 자동 발송 스위치 — 기본 꺼짐(fail-closed), 켜기 전까지 수동 발송만
    payment_alert_auto_send: bool = False
    payment_alert_auto_days: int = 3     # 자동 발송 대상: 감지 후 N일 이내 건만
    # 자동발송 운영 시작일(YYYY-MM-DD) — 이 날짜 이후 '입금일' 건만 자동발송.
    # 비어 있으면 스위치가 켜져 있어도 자동발송이 돌지 않는다(과거 건 오발송 방지).
    payment_alert_start_date: str = ""

    @property
    def is_bizppurio_configured(self) -> bool:
        return all(
            (self.bizppurio_sender_key, self.bizppurio_template_code, self.bizppurio_send_phone)
        )

    @property
    def is_database_configured(self) -> bool:
        return all((self.mssql_server, self.mssql_db, self.mssql_user))

    @property
    def is_kapa_configured(self) -> bool:
        return bool(self.kapa_lawrep_user and self.kapa_lawrep_pw.get_secret_value())

    @property
    def is_smtp_configured(self) -> bool:
        """메일 발송 설정이 다 있나 — 하나라도 비면 보내지 않는다(fail-closed)."""
        return all((
            self.smtp_host,
            self.smtp_user,
            self.smtp_password.get_secret_value(),
        ))

    @property
    def is_card_source_configured(self) -> bool:
        return all(
            (
                self.card_source_server,
                self.card_source_user,
                self.card_source_password.get_secret_value(),
            )
        )

    @property
    def is_popbill_configured(self) -> bool:
        return all(
            (
                self.popbill_link_id,
                self.popbill_secret_key.get_secret_value(),
                self.popbill_corp_num,
            )
        )

    @property
    def is_amaranth_configured(self) -> bool:
        return all(
            (
                self.a10_base_url,
                self.a10_caller_name,
                self.a10_access_token.get_secret_value(),
                self.a10_hash_key.get_secret_value(),
                self.a10_group_seq,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
