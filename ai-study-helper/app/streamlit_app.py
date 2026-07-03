"""AI 학습 도우미 — Streamlit 웹 UI (계획서 7장).

구성:
- 사이드바: 분석한 자료 히스토리 (job 목록) + 새 분석
- 입력 화면: 파일 업로드(영상/오디오/문서) 또는 유튜브 링크 + 노트 상세도
- 결과 화면 6탭: 노트 / 요약·목차 / 퀴즈 / 플래시카드 / 마인드맵 / 질문하기

파이프라인은 이 프로세스에서 인라인 실행한다(st.status로 단계 표시).
각 모듈에 체크포인트가 있어 재실행·재접속 시 완료 단계는 즉시 통과하고,
대용량 비동기 처리가 필요하면 7단계의 FastAPI+Celery 서버 모드를 쓰면 된다.

실행: .venv\\Scripts\\streamlit run app/streamlit_app.py
"""

import json
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config

BRAND = "렉처메이트"
BRAND_EN = "LectureMate"
TAGLINE = "강의, 유튜브, 논문까지 — 넣으면 노트·퀴즈·플래시카드가 자동으로 완성됩니다."

st.set_page_config(
    page_title=f"{BRAND} — AI 학습 도우미", page_icon="🎓", layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- 제품 스타일 ----------
# 팔레트: 흰 배경 + 진한 타이포(#111827) + 스카이블루 프라이머리(#06B2FC)
# + 핑크 포인트(#F653A2). 파스텔 틴트(#E6F7FF, #FEEEF6)로 배지·칩 처리.
st.markdown("""
<style>
/* Streamlit 기본 크롬 숨기기 — 제품처럼 보이게 */
#MainMenu, footer, [data-testid="stToolbar"], .stAppDeployButton { display: none !important; }
[data-testid="stHeader"] { background: transparent; }

/* 히어로 — 흰 바탕 + 큰 검정 헤드라인, 키워드만 블루 (클린 SaaS 스타일) */
.lm-hero { padding: 34px 8px 10px; text-align: center; }
.lm-hero .lm-badge {
  display: inline-block; background: #FEEEF6; color: #DB2777; border: 1px solid #FBCFE8;
  padding: 4px 14px; border-radius: 999px; font-size: .8rem; font-weight: 700; margin-bottom: 18px;
}
.lm-hero h1 {
  color: #111827; font-size: 2.6rem; line-height: 1.25; margin: 0 0 12px; letter-spacing: -1px; font-weight: 800;
}
.lm-hero h1 .hl { color: #06B2FC; }
.lm-hero p { color: #4B5563; font-size: 1.08rem; margin: 0 auto; max-width: 620px; }

/* 실측 수치 스트립 — 신뢰 요소 */
.lm-stat { text-align: center; padding: 18px 6px 14px; }
.lm-stat .n { font-size: 1.9rem; font-weight: 800; color: #06B2FC; letter-spacing: -0.5px; }
.lm-stat .n.pink { color: #F653A2; }
.lm-stat .d { color: #6B7280; font-size: .85rem; margin-top: 2px; }

/* 기능 카드 */
.lm-card {
  background: #fff; border: 1px solid #E5E7EB; border-radius: 16px;
  padding: 22px; height: 100%; box-shadow: 0 1px 4px rgba(17, 24, 39, .04);
}
.lm-card .lm-ic {
  display: inline-flex; width: 40px; height: 40px; align-items: center; justify-content: center;
  background: #E6F7FF; border-radius: 12px; font-size: 1.2rem;
}
.lm-card b { display: block; margin: 12px 0 4px; color: #111827; font-size: .98rem; }
.lm-card span { color: #6B7280; font-size: .87rem; line-height: 1.55; }

/* 3단계 사용법 */
.lm-step { text-align: center; padding: 10px 14px; }
.lm-step .no {
  display: inline-flex; width: 34px; height: 34px; align-items: center; justify-content: center;
  background: #06B2FC; color: #fff; border-radius: 999px; font-weight: 800; margin-bottom: 10px;
}
.lm-step b { display: block; color: #111827; margin-bottom: 4px; }
.lm-step span { color: #6B7280; font-size: .87rem; }

/* 결과 헤더 칩 */
.lm-chip {
  display: inline-block; background: #E6F7FF; color: #0369A1;
  padding: 4px 14px; border-radius: 999px; font-size: .82rem; font-weight: 600; margin-right: 8px;
}

/* 컨테이너(카드형) */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 14px !important; box-shadow: 0 1px 4px rgba(17, 24, 39, .03);
}

/* 탭 */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] { border-radius: 10px 10px 0 0; padding: 10px 18px; font-weight: 600; }

/* 버튼 — 플랫 스카이블루 */
.stButton > button[kind="primary"], .stFormSubmitButton > button {
  background: #06B2FC; border: none; font-weight: 700;
  box-shadow: 0 4px 12px rgba(6, 178, 252, .3);
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover { background: #0295D8; }

/* 사이드바 */
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E5E7EB; }
[data-testid="stSidebar"] .stButton > button { text-align: left; justify-content: flex-start; border-radius: 10px; }
.lm-side-brand { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.3px; color: #111827; }
.lm-side-brand em { font-style: normal; color: #06B2FC; }
.lm-side-sub { color: #9CA3AF; font-size: .78rem; margin-top: -4px; }
</style>
""", unsafe_allow_html=True)

UPLOAD_DIR = config.DATA_DIR / "uploads" / "ui"
MEDIA_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".mp3", ".m4a", ".wav", ".flac"}
DOC_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md"}


# ---------- 비밀번호(PIN) 게이트 (필수) ----------
# 4자리 비밀번호가 곧 계정이다: 등록(중복 불가) → 입장 → 자기 자료만 보임.
# 구글 OAuth는 실서비스 단계에서 교체 예정 (.streamlit/secrets.toml.example 참고).

from pin_auth import add_user_job, get_user_jobs, register_pin, verify_pin

if "user_id" not in st.session_state:
    st.markdown(
        f"""<div class="lm-hero" style="max-width:560px;margin:60px auto 24px;">
        <div class="lm-badge">✦ 비밀번호를 입력하세요</div>
        <h1 style="font-size:1.9rem;">🎓 {BRAND}</h1>
        <p>{TAGLINE}</p>
        </div>""",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        tab_enter, tab_new = st.tabs(["입장", "새 비밀번호 만들기"])
        with tab_enter:
            pin = st.text_input("비밀번호 (숫자 4자리)", type="password", max_chars=4, key="pin-enter")
            if st.button("입장", type="primary", use_container_width=True, key="btn-enter"):
                user_id = verify_pin(pin)
                if user_id:
                    st.session_state.user_id = user_id
                    st.rerun()
                else:
                    st.error("등록되지 않은 비밀번호입니다.")
        with tab_new:
            new_pin = st.text_input("사용할 비밀번호 (숫자 4자리)", type="password", max_chars=4, key="pin-new")
            new_pin2 = st.text_input("한 번 더 입력", type="password", max_chars=4, key="pin-new2")
            if st.button("등록하고 시작하기", type="primary", use_container_width=True, key="btn-new"):
                if new_pin != new_pin2:
                    st.error("두 입력이 일치하지 않습니다.")
                else:
                    user_id, err = register_pin(new_pin)
                    if err:
                        st.error(err)  # 형식 오류 또는 중복
                    else:
                        st.session_state.user_id = user_id
                        st.rerun()
    st.stop()


# ---------- 데이터 접근 ----------

def list_jobs() -> list[dict]:
    """분석 히스토리: 현재 사용자 소유 job만, 최신순으로 (비밀번호별 격리)."""
    jobs = []
    if not config.JOBS_DIR.exists():
        return jobs
    owned = set(get_user_jobs(st.session_state.user_id))
    for meta_path in config.JOBS_DIR.glob("*/meta.json"):
        if meta_path.parent.name not in owned:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        name = meta["source"].split("\\")[-1].split("/")[-1] if meta["source_type"] != "youtube" else meta["source"]
        jobs.append({
            "job_id": meta["job_id"],
            "name": name[:40],
            "type": meta["source_type"],
            "mtime": meta_path.stat().st_mtime,
            "done": (meta_path.parent / "notes.md").exists(),
        })
    return sorted(jobs, key=lambda j: j["mtime"], reverse=True)


def job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def load_json(job_id: str, filename: str):
    path = job_dir(job_id) / filename
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ---------- 파이프라인 인라인 실행 ----------

def run_pipeline_ui(source: str, detail: str, youtube_video: bool = True) -> str:
    """분석을 백그라운드 워커 큐에 등록하고 즉시 job_id를 반환한다.

    브라우저를 닫아도 분석은 워커에서 계속되고, 재접속하면 진행률/결과가 보인다.
    (이전의 세션 내 인라인 실행은 브라우저를 닫으면 중단되는 문제가 있었다.)
    """
    from kombu.exceptions import OperationalError

    from worker.tasks import enqueue_pipeline

    try:
        job_id = enqueue_pipeline(source, detail=detail, youtube_video=youtube_video)
    except OperationalError:
        st.error(
            "백그라운드 워커(Redis)가 꺼져 있습니다.\n\n"
            "프로젝트 폴더에서 `run_all.ps1`을 실행해 서비스 전체를 켜주세요."
        )
        st.stop()
    add_user_job(st.session_state.user_id, job_id)  # 시작 시점 소유 등록
    return job_id


def render_progress(job_id: str) -> None:
    """진행 중 화면: 단계별 상태 + 전체 진행률 + 예상 남은 시간. 4초마다 갱신."""
    from src import status as status_mod

    data = status_mod.read_status(job_id)
    if data is None:
        st.warning("분석 상태 정보가 없습니다. 같은 입력으로 다시 분석을 시작하면 이어서 진행됩니다.")
        return

    if data["state"] == "error":
        st.error(f"분석 중 오류가 발생했습니다: {data['error']}\n\n같은 입력으로 다시 시작하면 중단 지점부터 재개합니다.")
        return

    st.markdown("### 🔬 분석 진행 중")
    st.caption("브라우저를 닫아도 분석은 계속됩니다. 나중에 다시 접속해도 됩니다.")

    overall = status_mod.overall_progress(data)
    st.progress(overall, text=f"전체 {overall:.0%}")

    eta = status_mod.estimate_remaining(job_id, data)
    if eta:
        remaining, total = eta
        if remaining >= 90:
            st.info(f"⏱ 예상 남은 시간: 약 **{remaining / 60:.0f}분** (총 예상 {total / 60:.0f}분)")
        else:
            st.info("⏱ 예상 남은 시간: **1분 이내**")

    stage_names = {
        "ingest": "① 입력 접수·오디오 추출", "transcribe": "② GPU 음성 인식",
        "slides": "③ 슬라이드 비전 분석", "align": "④ 음성·화면 정렬",
        "notes": "⑤ 노트·요약·목차", "index": "⑥ 질문 인덱스",
    }
    icons = {"done": "✅", "skipped": "⏭️", "running": "🔄", "error": "❌", "pending": "⬜"}
    for key, label in stage_names.items():
        entry = data["stages"].get(key, {})
        icon = icons.get(entry.get("status", "pending"), "⬜")
        pct = f" — {entry.get('progress', 0):.0%}" if entry.get("status") == "running" else ""
        st.markdown(f"{icon} {label}{pct}")

    time.sleep(4)
    st.rerun()


# ---------- 사이드바 ----------

with st.sidebar:
    st.markdown(
        f'<div class="lm-side-brand">🎓 {BRAND}<em>.</em></div>'
        f'<div class="lm-side-sub">{BRAND_EN} — AI Study Companion</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"👤 사용자 {st.session_state.user_id[:5]}")
    if st.button("로그아웃", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.write("")
    if st.button("➕ 새 분석", type="primary", use_container_width=True):
        st.session_state.pop("job_id", None)
        st.rerun()

    st.subheader("내 학습 자료")
    for job in list_jobs():
        icon = {"video": "🎬", "audio": "🎵", "youtube": "▶️", "document": "📄"}.get(job["type"], "📦")
        mark = "" if job["done"] else " ⏳"
        if st.button(f"{icon} {job['name']}{mark}", key=f"job-{job['job_id']}", use_container_width=True):
            st.session_state.job_id = job["job_id"]
            st.rerun()


# ---------- 입력 화면 ----------

if "job_id" not in st.session_state:
    st.markdown(
        f"""<div class="lm-hero">
        <div class="lm-badge">✦ 슬라이드까지 읽는 멀티모달 AI</div>
        <h1>2시간 강의, <span class="hl">30분 만에</span><br/>시험 준비 끝.</h1>
        <p>{TAGLINE}</p>
        </div>""",
        unsafe_allow_html=True,
    )

    # 신뢰 요소: 실측 수치 (사회적 증거 대신 성능 증거)
    s1, s2, s3, s4 = st.columns(4)
    for col, (n, d, pink) in zip(
        [s1, s2, s3, s4],
        [
            ("52배", "실시간 대비 음성 인식 속도 (GPU)", False),
            ("110장", "2시간 강의에서 자동 분석된 슬라이드", False),
            ("6종", "노트·요약·퀴즈·카드·마인드맵·Q&A", True),
            ("100%", "모든 답변에 근거(타임스탬프) 표시", False),
        ],
    ):
        col.markdown(
            f'<div class="lm-stat"><div class="n{" pink" if pink else ""}">{n}</div><div class="d">{d}</div></div>',
            unsafe_allow_html=True,
        )
    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    for col, (ic, title, desc) in zip(
        [c1, c2, c3, c4],
        [
            ("🎬", "영상 · 유튜브 · 문서", "강의 영상, 유튜브 링크, PDF·PPT·논문까지 한 곳에서."),
            ("👁️", "화면까지 이해하는 AI", "음성만 듣지 않습니다. 슬라이드 속 표·그래프·코드까지 읽습니다."),
            ("📝", "학습 자료 자동 생성", "구조화 노트, 난이도별 퀴즈, 플래시카드, 마인드맵, 용어집."),
            ("💬", "근거 있는 Q&A", "질문하면 슬라이드 번호와 타임스탬프 근거로 답합니다."),
        ],
    ):
        col.markdown(
            f'<div class="lm-card"><div class="lm-ic">{ic}</div><b>{title}</b><span>{desc}</span></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown("#### 이렇게 사용하세요")
    t1, t2, t3 = st.columns(3)
    for col, (no, title, desc) in zip(
        [t1, t2, t3],
        [
            ("1", "자료 업로드", "강의 영상·유튜브 링크·문서를 넣고 분석 시작을 누르세요."),
            ("2", "AI가 알아서 분석", "음성 인식과 슬라이드 분석이 자동으로 진행됩니다."),
            ("3", "바로 공부 시작", "노트로 복습하고, 퀴즈로 점검하고, 궁금한 건 질문하세요."),
        ],
    ):
        col.markdown(
            f'<div class="lm-step"><div class="no">{no}</div><b>{title}</b><span>{desc}</span></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    detail = st.select_slider("노트 상세도", options=["하", "중", "상"], value="중")

    tab_file, tab_yt, tab_path = st.tabs(["📁 파일 업로드", "▶️ 유튜브 링크", "💾 대용량 파일 (경로)"])
    with tab_file:
        uploaded = st.file_uploader(
            "영상 · 오디오 · 문서 (PDF/Word/PPT/Excel/TXT/MD) — 4GB 이하",
            type=[e.lstrip(".") for e in sorted(MEDIA_EXTS | DOC_EXTS)],
        )
        if uploaded and st.button("분석 시작", type="primary", key="start-file"):
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            saved = UPLOAD_DIR / uploaded.name
            saved.write_bytes(uploaded.getbuffer())
            st.session_state.job_id = run_pipeline_ui(str(saved), detail)
            st.rerun()

    with tab_yt:
        url = st.text_input("유튜브 URL", placeholder="https://www.youtube.com/watch?v=...")
        with_video = st.checkbox(
            "슬라이드 분석 포함 (영상 다운로드, 권장)", value=True,
            help="강의 화면 속 PPT·칠판까지 분석합니다. 끄면 오디오만 받아 더 빠르지만 화면 정보를 잃습니다.",
        )
        if url and st.button("분석 시작", type="primary", key="start-yt"):
            st.session_state.job_id = run_pipeline_ui(url, detail, youtube_video=with_video)
            st.rerun()

    with tab_path:
        st.caption(
            "이 PC에 있는 파일은 업로드 없이 경로로 바로 분석합니다 — 10GB급 영상도 복사 없이 처리 "
            "(원본은 읽기만 하고 수정하지 않습니다)."
        )
        local_path = st.text_input("파일 경로", placeholder=r"D:\강의\lecture.mp4")
        if local_path and st.button("분석 시작", type="primary", key="start-path"):
            p = Path(local_path.strip().strip('"'))
            if not p.exists():
                st.error(f"파일을 찾을 수 없습니다: {p}")
            elif p.suffix.lower() not in MEDIA_EXTS | DOC_EXTS:
                st.error(f"지원하지 않는 형식입니다: {p.suffix}")
            else:
                st.session_state.job_id = run_pipeline_ui(str(p), detail)
                st.rerun()
    st.stop()


# ---------- 결과 화면 ----------

job_id = st.session_state.job_id
chapters_data = load_json(job_id, "chapters.json") or {}
notes_path = job_dir(job_id) / "notes.md"

if not notes_path.exists():
    render_progress(job_id)  # 진행률 + 예상 시간, 자동 갱신
    st.stop()

# 결과 헤더: 자료명 + 요약 통계 칩
_meta = load_json(job_id, "meta.json") or {}
_aligned = load_json(job_id, "aligned.json") or []
_src_name = (_meta.get("source", "")).split("\\")[-1].split("/")[-1]
_chips = []
if _aligned and _aligned[-1].get("end"):
    from src.transcribe import format_timestamp as _fmt

    _chips.append(f"⏱ {_fmt(_aligned[-1]['end'])}")
if _meta.get("video_path"):
    _chips.append(f"🖼 슬라이드 {len(_aligned)}장")
if chapters_data.get("chapters"):
    _chips.append(f"📚 챕터 {len(chapters_data['chapters'])}개")
st.markdown(
    f"### {_src_name or '학습 자료'}  \n"
    + "".join(f'<span class="lm-chip">{c}</span>' for c in _chips),
    unsafe_allow_html=True,
)
st.write("")

tab_notes, tab_summary, tab_quiz, tab_cards, tab_map, tab_ask = st.tabs(
    ["📝 노트", "📋 요약·목차", "❓ 퀴즈", "🃏 플래시카드", "🧠 마인드맵", "💬 질문하기"]
)

with tab_notes:
    notes_md = notes_path.read_text(encoding="utf-8")
    # notes.md = 요약+목차+본문. 노트 탭은 본문만 (요약·목차는 옆 탭에서 시각적으로)
    body = notes_md.split("# 학습 노트", 1)
    st.markdown(body[1] if len(body) == 2 else notes_md)

    st.divider()
    st.subheader("📖 용어집")
    glossary_data = load_json(job_id, "glossary.json")
    if st.button("생성" if not glossary_data else "재생성", key="gen-glossary"):
        from src.generate import generate_glossary

        with st.spinner("용어집 생성 중..."):
            generate_glossary(job_id)
        st.rerun()
    if glossary_data:
        st.table(
            [{"용어": t["term"], "한국어": t["korean"], "설명": t["definition"]} for t in glossary_data["terms"]]
        )

with tab_summary:
    st.subheader("요약")
    st.write(chapters_data.get("summary", "요약이 없습니다."))
    st.subheader("시간대별 목차")
    from src.transcribe import format_timestamp

    for ch in chapters_data.get("chapters", []):
        with st.container(border=True):
            col_img, col_txt = st.columns([1, 3])
            aligned = load_json(job_id, "aligned.json") or []
            images = {s["slide_index"]: s["slide_image"] for s in aligned}
            thumb = next((images.get(i) for i in ch.get("slides", []) if images.get(i)), None)
            with col_img:
                if thumb and Path(thumb).exists():
                    st.image(thumb)
            with col_txt:
                st.markdown(f"**[{format_timestamp(ch['start'])} ~ {format_timestamp(ch['end'])}] {ch['title']}**")
                if ch.get("slides"):
                    st.caption(f"슬라이드 {', '.join(map(str, ch['slides'][:8]))}")

with tab_quiz:
    from src.generate import DIFFICULTIES, Quiz, generate_quiz, grade_answer

    col1, col2, col3 = st.columns([2, 2, 1])
    difficulty = col1.selectbox("난이도", DIFFICULTIES, index=1)
    count = col2.number_input("문항 수", 3, 20, 8)
    quiz_file = f"quiz_{difficulty}.json"
    quiz_data = load_json(job_id, quiz_file)

    if col3.button("생성" if not quiz_data else "재생성", key="gen-quiz"):
        with st.spinner("퀴즈 생성 중..."):
            generate_quiz(job_id, count=int(count), difficulty=difficulty)
        st.session_state.pop("quiz_submitted", None)
        st.rerun()

    if quiz_data:
        quiz = Quiz(**quiz_data)
        answers = {}
        with st.form("quiz-form"):
            for i, q in enumerate(quiz.questions):
                st.markdown(f"**{i + 1}. {q.question}**")
                if q.type == "multiple_choice":
                    answers[i] = st.radio("보기", q.options, key=f"q{i}", index=None, label_visibility="collapsed")
                else:
                    answers[i] = st.text_input("답", key=f"q{i}", label_visibility="collapsed")
            submitted = st.form_submit_button("제출·채점", type="primary")
        if submitted:
            correct = 0
            for i, q in enumerate(quiz.questions):
                user = answers.get(i) or ""
                ok = grade_answer(q, user)
                correct += ok
                with st.expander(f"{'✅' if ok else '❌'} {i + 1}번 — 정답: {q.answer}", expanded=not ok):
                    st.write(q.explanation)
                    if q.source_slide:
                        st.caption(f"근거: 슬라이드 {q.source_slide}")
            st.metric("점수", f"{correct} / {len(quiz.questions)}")

with tab_cards:
    from src.generate import FlashcardDeck, generate_flashcards

    deck_data = load_json(job_id, "flashcards.json")
    if st.button("생성" if not deck_data else "재생성", key="gen-cards"):
        with st.spinner("플래시카드 생성 중..."):
            generate_flashcards(job_id)
        st.session_state.card_idx = 0
        st.rerun()

    if deck_data:
        deck = FlashcardDeck(**deck_data)
        idx = st.session_state.get("card_idx", 0) % len(deck.cards)
        card = deck.cards[idx]

        st.caption(f"{idx + 1} / {len(deck.cards)}")
        with st.container(border=True):
            st.markdown(f"### {card.front}")
            if st.toggle("답 보기", key=f"flip-{idx}"):
                st.success(card.back)
                if card.source_slide:
                    st.caption(f"근거: 슬라이드 {card.source_slide}")
        col_prev, col_next = st.columns(2)
        if col_prev.button("← 이전", use_container_width=True):
            st.session_state.card_idx = (idx - 1) % len(deck.cards)
            st.rerun()
        if col_next.button("다음 →", use_container_width=True):
            st.session_state.card_idx = (idx + 1) % len(deck.cards)
            st.rerun()

with tab_map:
    import streamlit.components.v1 as components

    from src.generate import generate_mindmap

    map_path = job_dir(job_id) / "mindmap.html"
    if st.button("생성" if not map_path.exists() else "재생성", key="gen-map"):
        with st.spinner("마인드맵 생성 중..."):
            generate_mindmap(job_id)
        st.rerun()
    if map_path.exists():
        components.html(map_path.read_text(encoding="utf-8"), height=650, scrolling=True)

with tab_ask:
    from src.rag import ask

    if "chat" not in st.session_state:
        st.session_state.chat = []
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.write(msg["text"])
            if msg.get("sources"):
                st.caption("근거: " + " · ".join(msg["sources"]))

    if question := st.chat_input("강의 내용에 대해 질문하세요"):
        st.session_state.chat.append({"role": "user", "text": question})
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("근거 검색·답변 생성 중..."):
                answer = ask(job_id, question)
            st.write(answer.text)
            labels = [s.label for s in answer.sources]
            st.caption("근거: " + " · ".join(labels))
        st.session_state.chat.append({"role": "assistant", "text": answer.text, "sources": labels})
