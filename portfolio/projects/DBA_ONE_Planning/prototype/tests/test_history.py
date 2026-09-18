"""이력 저장 회귀 테스트 — 연결별(target_id) 격리, legacy 이관, v1→v2 마이그레이션.

실행: prototype 디렉터리에서  python -m unittest discover tests -v
"""
import sqlite3
import unittest
from datetime import datetime, timedelta

from tests._bootstrap import app


def _seed_query_snap(conn_id, ts, query_id, avg_ms):
    with sqlite3.connect(app.HIST_PATH) as c:
        c.execute("INSERT INTO query_snap VALUES (?,?,?,?,?,?,?)",
                  (conn_id, ts, query_id, "obj", avg_ms, 10, 100))


class TestConnIsolation(unittest.TestCase):
    """서버 전환 시 시계열·알림·기준선이 섞이지 않아야 한다."""

    @classmethod
    def setUpClass(cls):
        app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        app.init_history()

    def setUp(self):
        self._saved = (app.TARGET_ID, app.DB_LIVE)

    def tearDown(self):
        app.TARGET_ID, app.DB_LIVE = self._saved

    def test_baselines_scoped_to_target(self):
        old = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(3):  # SRV1에만 표본 3개 (기준선 성립 조건)
            _seed_query_snap("SRV1/db", old, 101, 100.0)
        _seed_query_snap("SRV2/db", old, 101, 900.0)
        app.TARGET_ID = "SRV1/db"
        self.assertEqual(app.query_baselines([101]).get(101), 100.0)
        app.TARGET_ID = "SRV2/db"  # 표본 1개뿐 — 기준선 없음
        self.assertEqual(app.query_baselines([101]), {})

    def test_alerts_scoped_to_target(self):
        app.DB_LIVE = True  # list_alerts의 데모 분기 우회 (sqlite만 접근)
        app.TARGET_ID = "SRV1/db"
        app._upsert_alert("blocking", "serious", "블로킹", "원인", "조치")
        self.assertEqual(app.list_alerts()["active_count"], 1)
        app.TARGET_ID = "SRV2/db"
        self.assertEqual(app.list_alerts()["active_count"], 0,
                         "다른 서버의 알림이 보이면 안 됨")

    def test_timeseries_scoped_to_target(self):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(app.HIST_PATH) as c:
            c.execute("INSERT INTO server_snap VALUES (?,?,?,?)", ("SRV1/db", ts, 5, 0))
        app.DB_LIVE = True
        app.TARGET_ID = "SRV1/db"
        self.assertEqual(len(app.get_timeseries("server", 24)["points"]), 1)
        app.TARGET_ID = "SRV2/db"
        self.assertEqual(len(app.get_timeseries("server", 24)["points"]), 0)


class TestObjectVersions(unittest.TestCase):
    def setUp(self):
        app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        app.init_history()
        self._saved = (app.TARGET_ID, dict(app.CONFIG))
        with sqlite3.connect(app.HIST_PATH) as c:
            c.execute("DELETE FROM obj_versions")

    def tearDown(self):
        app.TARGET_ID = self._saved[0]
        app.CONFIG.clear()
        app.CONFIG.update(self._saved[1])

    def test_diff_between_versions(self):
        app.TARGET_ID = "SRV1/db"
        with sqlite3.connect(app.HIST_PATH) as c:
            c.execute("INSERT INTO obj_versions VALUES (?,?,?,?,?,?)",
                      ("2026-07-21 10:00:00", "SRV1/db", "dbo.SP_X", "2026-07-21 09:00:00",
                       "SELECT a\nFROM t", "baseline"))
            c.execute("INSERT INTO obj_versions VALUES (?,?,?,?,?,?)",
                      ("2026-07-21 11:00:00", "SRV1/db", "dbo.SP_X", "2026-07-21 10:55:00",
                       "SELECT a, b\nFROM t", "changed"))
        vd = app.object_version_diff("SP_X")  # 스키마 없이도 매칭
        self.assertEqual(vd["versions"], 2)
        self.assertIn("+SELECT a, b", vd["diff"])
        self.assertIn("-SELECT a", vd["diff"])

    def test_adopt_legacy_moves_and_verifies(self):
        app.CONFIG["mssql_conn"] = 'SERVER=192.0.2.10;DATABASE=db1;UID=u;PWD={p}'
        app.TARGET_ID = "REALSRV/db1"
        with sqlite3.connect(app.HIST_PATH) as c:
            for i in range(3):
                c.execute("INSERT INTO obj_versions VALUES (?,?,?,?,?,?)",
                          (f"2026-07-21 10:0{i}:00", 'legacy:192.0.2.10/db1',
                           f"dbo.SP_{i}", "2026-07-21", "src", "baseline"))
        app.adopt_legacy_versions()
        with sqlite3.connect(app.HIST_PATH) as c:
            n_target = c.execute("SELECT COUNT(*) FROM obj_versions WHERE conn=?",
                                 ("REALSRV/db1",)).fetchone()[0]
            n_legacy = c.execute("SELECT COUNT(*) FROM obj_versions WHERE conn LIKE 'legacy:%'"
                                 ).fetchone()[0]
        self.assertEqual((n_target, n_legacy), (3, 0))

    def test_adopt_never_merges_into_existing_target(self):
        app.CONFIG["mssql_conn"] = 'SERVER=192.0.2.10;DATABASE=db1;UID=u;PWD={p}'
        app.TARGET_ID = "REALSRV/db1"
        with sqlite3.connect(app.HIST_PATH) as c:
            c.execute("INSERT INTO obj_versions VALUES (?,?,?,?,?,?)",
                      ("2026-07-21 10:00:00", "REALSRV/db1", "dbo.SP_A", "m", "s", "baseline"))
            c.execute("INSERT INTO obj_versions VALUES (?,?,?,?,?,?)",
                      ("2026-07-21 10:00:00", 'legacy:192.0.2.10/db1', "dbo.SP_B", "m", "s", "baseline"))
        app.adopt_legacy_versions()  # target에 이력이 있으므로 병합 금지
        with sqlite3.connect(app.HIST_PATH) as c:
            n_legacy = c.execute("SELECT COUNT(*) FROM obj_versions WHERE conn LIKE 'legacy:%'"
                                 ).fetchone()[0]
        self.assertEqual(n_legacy, 1, "임의 병합이 일어나면 안 됨")


class TestMigrationV2(unittest.TestCase):
    def test_v1_db_backed_up_and_rebuilt(self):
        app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        saved = app.HIST_PATH
        app.HIST_PATH = app.DATA_DIR / "history_migtest.db"
        try:
            with sqlite3.connect(app.HIST_PATH) as c:  # v1 스키마 위조
                c.execute("CREATE TABLE server_snap (ts TEXT, sessions INTEGER, blocked INTEGER)")
                c.execute("INSERT INTO server_snap VALUES ('2026-07-20 10:00:00', 5, 0)")
                c.execute("CREATE TABLE obj_versions (ts TEXT, conn TEXT, obj_name TEXT,"
                          " modify_date TEXT, definition TEXT, reason TEXT)")
                c.execute("INSERT INTO obj_versions VALUES ('t','srv/db','dbo.SP_X','m','src','baseline')")
                c.execute("PRAGMA user_version = 0")
            app.migrate_history_v2()
            backups = list(app.DATA_DIR.glob("history_backup_*.db"))
            self.assertTrue(backups, "백업 파일이 생성돼야 함")
            with sqlite3.connect(app.HIST_PATH) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)
                conn_val = c.execute("SELECT conn FROM obj_versions").fetchone()[0]
                self.assertEqual(conn_val, "legacy:srv/db", "정의 버전은 legacy로 보존")
                cols = [r[1] for r in c.execute("PRAGMA table_info(server_snap)").fetchall()]
                self.assertIn("conn", cols, "v2 스키마에 conn 컬럼 필요")
                self.assertEqual(c.execute("SELECT COUNT(*) FROM server_snap").fetchone()[0], 0,
                                 "귀속 불가 시계열은 폐기(백업에만 보존)")
                self.assertEqual(c.execute("PRAGMA quick_check").fetchone()[0], "ok")
        finally:
            app.HIST_PATH = saved


if __name__ == "__main__":
    unittest.main()
