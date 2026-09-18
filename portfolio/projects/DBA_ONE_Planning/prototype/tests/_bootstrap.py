"""테스트 격리 부트스트랩 — app import 전에 임시 DATA_DIR을 지정한다.

실 config.json·history.db·Gemini 키에 접근하면 즉시 실패한다.
모든 테스트 모듈은 `from tests._bootstrap import app`으로 app을 가져온다.
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="dbaone_test_")).resolve()
os.environ["DBAONE_DATA_DIR"] = str(TMP)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GEMINI_MODEL", None)
os.environ.pop("DBAONE_MSSQL_CONN", None)
os.environ.pop("DBAONE_UNSAFE_ALLOW_PRIVILEGED_RUN", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402

assert app.DATA_DIR == TMP, f"임시 DATA_DIR 격리 실패: {app.DATA_DIR}"
assert not app.DB_LIVE, "테스트가 실 DB 설정을 읽음 — 격리 실패"
assert not app.AI_ON, "테스트가 실 API 키를 읽음 — 격리 실패"
