import unittest

import bankonline_ts as B
import config


def app_cfg():
    app = config.AppConfig()
    app.login = config.Login(
        save_credentials=True,
        bank24_id="uid",
        bank24_pw="pwd",
    )
    app.bankonline = config.BankOnline(
        enabled=True,
        endpoint="https://example.invalid/REST_BANK_JUBSU_UPD",
        authorization="token",
    )
    return app


class TestBankOnlineTS(unittest.TestCase):
    def test_payload_uses_ts_gubun_and_new_master_id(self):
        payload = B.build_payload({
            "RequestNo": "T260704561",
            "NewMasterID": "01-20260709-001",
            "Bank": "우리은행",
        }, app_cfg())
        self.assertEqual(payload["Procedure"], "REST_BANK_JUBSU_UPD")
        self.assertEqual(payload["UPMU_GUBUN"], "2")
        self.assertEqual(payload["DAMBO_NO"], "T260704561")
        self.assertEqual(payload["GAM_NO"], "01-20260709-001")
        self.assertEqual(payload["CUSTKEY"], "WRB")
        self.assertEqual(payload["APPCODE"], "300611")

    def test_missing_new_master_id_blocks_payload(self):
        self.assertEqual(B.build_payload({
            "RequestNo": "T260704561",
            "Bank": "우리은행",
        }, app_cfg()), {})

    def test_disabled_does_not_call_api(self):
        app = app_cfg()
        app.bankonline.enabled = False
        called = []
        status, err = B.call({
            "RequestNo": "T260704561",
            "NewMasterID": "01-20260709-001",
            "Bank": "우리은행",
        }, app, caller=lambda p: called.append(p) or True)
        self.assertEqual((status, err), ("", "DISABLED"))
        self.assertEqual(called, [])

    def test_call_sends_payload_to_caller(self):
        seen = []
        status, err = B.call({
            "RequestNo": '000000-0000000',
            "NewMasterID": "01-20260709-002",
            "Bank": "국민은행",
        }, app_cfg(), caller=lambda p: seen.append(p) or True)
        self.assertEqual((status, err), ("Y", ""))
        self.assertEqual(seen[0]["UPMU_GUBUN"], "2")
        self.assertEqual(seen[0]["GAM_NO"], "01-20260709-002")

    def test_imbank_payload_uses_dgb_custkey(self):
        payload = B.build_payload({
            "RequestNo": 'KAP000000-0000000',
            "NewMasterID": "01-20260710-084",
            "Bank": "아이엠뱅크 PRM강남2센터",
        }, app_cfg())
        self.assertEqual(payload["CUSTKEY"], "DGB")
        self.assertEqual(payload["DAMBO_NO"], 'KAP000000-0000000')

    def test_call_logs_invalid_payload_reason_without_secrets(self):
        app = app_cfg()
        app.login.bank24_pw = ""
        logs = []
        status, err = B.call({
            "RequestNo": '000000-0000000',
            "Bank": "국민은행",
        }, app, logger=logs.append)
        joined = "\n".join(logs)
        self.assertEqual((status, err), ("N", "INVALID_PAYLOAD"))
        self.assertIn("GAM_NO_MISSING", joined)
        self.assertIn("PWD_MISSING", joined)
        self.assertIn("DAMBO_NO=*********1008", joined)
        self.assertNotIn('000000-0000000', joined)

    def test_call_logs_api_rejected(self):
        logs = []
        status, err = B.call({
            "RequestNo": '000000-0000000',
            "NewMasterID": "01-20260709-002",
            "Bank": "국민은행",
        }, app_cfg(), caller=lambda p: False, logger=logs.append)
        self.assertEqual((status, err), ("N", "API_REJECTED"))
        self.assertTrue(any("API_REJECTED" in x for x in logs))

    def test_call_rest_logs_non_json_response_preview(self):
        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b"RESULT 1234567890"
            def getcode(self): return 200

        app = app_cfg()
        old_urlopen = B.urllib.request.urlopen
        logs = []
        try:
            B.urllib.request.urlopen = lambda req, timeout: Resp()
            self.assertFalse(B.call_rest({
                "Procedure": "REST_BANK_JUBSU_UPD",
            }, app, logger=logs.append))
        finally:
            B.urllib.request.urlopen = old_urlopen
        joined = "\n".join(logs)
        self.assertIn("응답 JSON 파싱 실패", joined)
        self.assertIn("******7890", joined)
        self.assertNotIn('REDACTED_CONFIGURE_LOCALLY7890', joined)

    def test_call_rest_accepts_procedure_success_text(self):
        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b"Procedure Success"
            def getcode(self): return 200

        app = app_cfg()
        old_urlopen = B.urllib.request.urlopen
        logs = []
        try:
            B.urllib.request.urlopen = lambda req, timeout: Resp()
            self.assertTrue(B.call_rest({
                "Procedure": "REST_BANK_JUBSU_UPD",
            }, app, logger=logs.append))
        finally:
            B.urllib.request.urlopen = old_urlopen
        self.assertTrue(any("Procedure Success" in x for x in logs))

    def test_resolve_authorization_fetches_token_when_not_configured(self):
        app = app_cfg()
        app.bankonline.authorization = ""
        app.bankonline.token_endpoint = "https://authtoken.kapanet.or.kr/AuthServer"
        old_cred, old_token = B.fetch_kapa_credentials, B.fetch_token
        try:
            B.fetch_kapa_credentials = lambda cfg: ("kid", "kpw")
            B.fetch_token = lambda kid, kpw, cfg: f"tok-{kid}-{kpw}"
            self.assertEqual(B.resolve_authorization(app), "tok-kid-kpw")
        finally:
            B.fetch_kapa_credentials, B.fetch_token = old_cred, old_token

    def test_configured_authorization_skips_token_fetch(self):
        app = app_cfg()
        app.bankonline.authorization = "already-issued"
        old_cred = B.fetch_kapa_credentials
        try:
            B.fetch_kapa_credentials = lambda cfg: (_ for _ in ()).throw(AssertionError("called"))
            self.assertEqual(B.resolve_authorization(app), "already-issued")
        finally:
            B.fetch_kapa_credentials = old_cred


if __name__ == "__main__":
    unittest.main()
