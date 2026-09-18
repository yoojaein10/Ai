"""
도매매/오너클랜 위탁판매 ERP - 관리자 대시보드 v2
실행: streamlit run ecommerce_admin.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    st.error("DATABASE_URL 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
    st.stop()
API_URL = os.getenv("API_URL", "http://localhost:8000")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)


def _run_async(coro):
    """Streamlit 환경에서 비동기 함수를 실행합니다."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── 페이지 설정 ──────────────────────────────────────
st.set_page_config(page_title="위탁판매 ERP", page_icon="📦", layout="wide")
st.title("📦 위탁판매 ERP")
st.caption("도매꾹 / 오너클랜 → 쿠팡 / 스마트스토어 위탁판매 자동화")


# ── 데이터 로드 함수 ─────────────────────────────────
@st.cache_data(ttl=10)
def load_products(source_filter: str = "ALL") -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM products ORDER BY id DESC", engine)
    if source_filter != "ALL":
        df = df[df["source"] == source_filter]
    return df


@st.cache_data(ttl=300)
def load_recommendations(
    limit: int = 20,
    sources: list[str] | None = None,
    sort_by: str = "sales",
) -> list[dict]:
    from services.recommend_service import fetch_recommendations
    results = _run_async(fetch_recommendations(limit, sources, sort_by))
    return [
        {"source": r.source, "item_no": r.item_no, "title": r.title,
         "price": r.price, "image": r.image, "category": r.category}
        for r in results
    ]


def _crawl_product(source: str, item_no: str) -> dict | None:
    """API를 통해 상품을 수집합니다."""
    import httpx
    try:
        resp = httpx.post(
            f"{API_URL}/collector/crawl",
            params={"source": source, "item_no": item_no},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"상품 수집 실패 ({source}/{item_no}): {e}")
    return None


# ══════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 설정 & 수집")

    # ── 필터 ──
    source_filter = st.selectbox(
        "도매처 필터",
        ["ALL", "DOMEME", "OWNERCLAN"],
        format_func=lambda x: {"ALL": "전체", "DOMEME": "도매꾹", "OWNERCLAN": "오너클랜"}.get(x, x),
    )

    st.divider()

    # ── 단일 상품 수집 ──
    st.subheader("📥 단일 상품 수집")
    col_source = st.selectbox("도매처", ["DOMEME", "OWNERCLAN"], key="crawl_source",
                              format_func=lambda x: {"DOMEME": "도매꾹", "OWNERCLAN": "오너클랜"}.get(x, x))
    col_item_no = st.text_input("상품번호", placeholder="예: 41326424")

    if st.button("수집 시작", type="primary", use_container_width=True):
        if col_item_no.strip():
            with st.spinner("수집 중..."):
                result = _crawl_product(col_source, col_item_no.strip())
            if result:
                st.success(f"수집 완료: {result.get('title', '')[:30]}")
                st.cache_data.clear()
            else:
                st.error("수집 실패")
        else:
            st.warning("상품번호를 입력하세요")

    st.divider()

    # ── 키워드 검색 수집 (뼈대) ──
    st.subheader("🔎 키워드 검색 수집")
    st.caption("도매꾹 키워드 검색")
    kw_text = st.text_input("검색 키워드", placeholder="예: 무선이어폰", key="kw_text")
    kw_count = st.slider("수집 개수", 1, 20, 5, key="kw_count")
    if st.button("키워드 수집", use_container_width=True, key="kw_btn"):
        if kw_text.strip():
            with st.status(f"'{kw_text}' 키워드 수집 중...", expanded=True) as status:
                st.write(f"도매꾹 키워드 검색: '{kw_text}'")
                from services.recommend_service import _fetch_domeme_by_keyword
                kw_results = _run_async(
                    _fetch_domeme_by_keyword(kw_text.strip(), limit=kw_count)
                )

                if not kw_results:
                    st.write("검색 결과가 없습니다.")
                    status.update(label="검색 결과 없음", state="error")
                else:
                    st.write(f"{len(kw_results)}개 상품 발견, DB 저장 중...")
                    success = 0
                    for item in kw_results:
                        st.write(f"  수집: {item.title[:30]}")
                        result = _crawl_product(item.source, item.item_no)
                        if result:
                            success += 1
                            st.write(f"    > 저장 완료")
                        else:
                            st.write(f"    > 실패")
                    status.update(
                        label=f"키워드 수집 완료! ({success}/{len(kw_results)} 성공)",
                        state="complete",
                    )
                    st.cache_data.clear()
        else:
            st.warning("검색 키워드를 입력하세요")

    st.divider()

    # ── 일괄 수집 (뼈대) ──
    st.subheader("📋 일괄 수집")
    batch_source = st.selectbox("도매처", ["DOMEME", "OWNERCLAN"], key="batch_source",
                                format_func=lambda x: {"DOMEME": "도매꾹", "OWNERCLAN": "오너클랜"}.get(x, x))
    batch_numbers = st.text_area("상품번호 (줄바꿈 구분)", placeholder="41326424\n41326425\n41326426", key="batch_nums")
    if st.button("일괄 수집 시작", use_container_width=True, key="batch_btn"):
        nums = [n.strip() for n in batch_numbers.strip().split("\n") if n.strip()]
        if nums:
            with st.status(f"일괄 수집 중... (0/{len(nums)})", expanded=True) as status:
                success = 0
                for i, num in enumerate(nums):
                    st.write(f"수집 중: {batch_source} #{num}")
                    result = _crawl_product(batch_source, num)
                    if result:
                        success += 1
                        st.write(f"  ✅ {result.get('title', '')[:30]}")
                    else:
                        st.write(f"  ❌ 실패")
                    status.update(label=f"일괄 수집 중... ({i+1}/{len(nums)})")
                status.update(label=f"일괄 수집 완료! ({success}/{len(nums)} 성공)", state="complete")
            st.cache_data.clear()
        else:
            st.warning("상품번호를 입력하세요")

    st.divider()
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()


# ══════════════════════════════════════════════════════
# 탭 구성 (3개)
# ══════════════════════════════════════════════════════
tab_sourcing, tab_products, tab_register = st.tabs(
    ["🔍 소싱 & 마진 분석", "📦 내 상품 관리", "🚀 마켓 등록 대기열"]
)


# ══════════════════════════════════════════════════════
# 탭 1: 소싱 & 마진 분석
# ══════════════════════════════════════════════════════
with tab_sourcing:

    # ── 컨트롤 패널 ──
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 1])
    with ctrl1:
        src_limit = st.slider("사이트당 수집 수", 10, 50, 25, key="src_limit")
    with ctrl2:
        src_sources = st.multiselect(
            "도매처",
            ["DOMEME", "OWNERCLAN"],
            default=["DOMEME", "OWNERCLAN"],
            format_func=lambda x: {"DOMEME": "🟦 도매꾹", "OWNERCLAN": "🟧 오너클랜"}.get(x, x),
            key="src_sources",
        )
    with ctrl3:
        src_with_margin = st.checkbox("마진 분석 포함", value=True, key="src_margin")
    with ctrl4:
        src_with_ai = st.checkbox("AI 소구점 생성", value=False, key="src_ai")

    # ── 카테고리 키워드 검색 ──
    st.markdown("##### 카테고리 키워드")
    _CAT_OPTIONS = ["수납정리", "주방용품", "욕실용품", "반려동물용품", "차량용품", "사무용품", "헬스용품"]
    ck_cols = st.columns(len(_CAT_OPTIONS) + 1)
    _ck_vals = {}
    for i, cat in enumerate(_CAT_OPTIONS):
        with ck_cols[i]:
            _ck_vals[cat] = st.checkbox(cat, key=f"ck_{cat}")
    with ck_cols[-1]:
        custom_kw = st.text_input("직접입력", placeholder="캠핑용품", key="custom_kw", label_visibility="collapsed")

    category_keywords = [cat for cat, checked in _ck_vals.items() if checked]
    if custom_kw.strip() and custom_kw.strip() not in category_keywords:
        category_keywords.append(custom_kw.strip())

    if category_keywords:
        st.caption(f"키워드 검색 모드: {', '.join(category_keywords)}")

    btn_cols = st.columns([2, 1])
    with btn_cols[0]:
        run_sourcing = st.button("🚀 추천 상품 불러오기 & 마진 분석", type="primary", use_container_width=True)
    with btn_cols[1]:
        if st.button("🗑️ 결과 초기화", use_container_width=True):
            st.session_state.pop("sourcing_recs", None)
            st.session_state.pop("margin_top10", None)
            st.rerun()

    # ── 실행 ──
    if run_sourcing:
        if not src_sources and not category_keywords:
            st.warning("도매처를 선택해 주세요.")
        else:
            with st.status("소싱 분석 진행 중...", expanded=True) as status:
                # Step 1: 상품 수집 (카테고리 키워드 모드 vs 기존 추천 모드)
                if category_keywords:
                    st.write(f"📡 카테고리 키워드 검색 중... ({', '.join(category_keywords)})")
                    from services.recommend_service import fetch_by_keywords
                    kw_products = _run_async(
                        fetch_by_keywords(category_keywords, limit_per_keyword=src_limit)
                    )
                    rec_items = [
                        {"source": r.source, "item_no": r.item_no, "title": r.title,
                         "price": r.price, "image": r.image, "category": r.category}
                        for r in kw_products
                    ]
                    st.write(f"✅ 키워드 검색 **{len(rec_items)}개** 수집 완료")
                else:
                    st.write("📡 도매꾹/오너클랜 상품 수집 중... (판매순 + 신상품순)")
                    sales_items = load_recommendations(src_limit, src_sources, "sales")
                    st.write(f"  🔥 판매순 **{len(sales_items)}개** 수집")
                    newest_items = load_recommendations(src_limit, src_sources, "newest")
                    st.write(f"  ✨ 신상품순 **{len(newest_items)}개** 수집")

                    # 중복 제거 (source + item_no 기준)
                    seen = set()
                    rec_items = []
                    for item in sales_items + newest_items:
                        key = (item["source"], item["item_no"])
                        if key not in seen:
                            seen.add(key)
                            rec_items.append(item)

                    dup_count = len(sales_items) + len(newest_items) - len(rec_items)
                    if rec_items:
                        st.write(f"✅ 추천 상품 **{len(rec_items)}개** 수집 완료 (중복 {dup_count}개 제거)")

                if not rec_items:
                    st.error("추천 상품을 가져올 수 없습니다.")
                else:
                    st.session_state["sourcing_recs"] = rec_items

                    # Step 2: 마진 분석
                    if src_with_margin:
                        st.write("💰 시장 최저가 조회 & 마진 분석 중...")
                        from services.analyzer_service import get_margin_top_10

                        progress = st.progress(0)

                        def margin_cb(cur, total, title=""):
                            progress.progress(cur / total, text=f"({cur}/{total}) {title[:25]}")

                        top10 = _run_async(get_margin_top_10(rec_items, margin_cb))
                        progress.empty()

                        if top10:
                            st.write(f"✅ 마진 TOP {len(top10)} 추출 완료")

                            # Step 3: AI 소구점
                            if src_with_ai:
                                st.write("🤖 AI 판매 소구점 생성 중... (2초 간격)")
                                from services.ai_service import generate_selling_points_batch
                                ai_items = [
                                    {"title": t.title, "cost_price": t.cost_price, "market_lowest": t.market_lowest}
                                    for t in top10
                                ]

                                ai_progress = st.progress(0)

                                def ai_cb(cur, total):
                                    ai_progress.progress(cur / total, text=f"AI ({cur}/{total})")

                                summaries = _run_async(
                                    generate_selling_points_batch(ai_items, ai_cb)
                                )
                                ai_progress.empty()
                                for i, s in enumerate(summaries):
                                    top10[i].ai_summary = s
                                st.write("✅ AI 소구점 생성 완료")

                            st.session_state["margin_top10"] = [
                                {
                                    "source": t.source, "item_no": t.item_no, "title": t.title,
                                    "image": t.image, "cost_price": t.cost_price,
                                    "market_lowest": t.market_lowest,
                                    "estimated_profit": t.estimated_profit,
                                    "margin_rate": t.margin_rate,
                                    "ai_summary": getattr(t, "ai_summary", "-"),
                                    "category": getattr(t, "category", ""),
                                }
                                for t in top10
                            ]

                    status.update(label="소싱 분석 완료!", state="complete")

    # ── 마진 TOP 10 결과 표시 ──
    if st.session_state.get("margin_top10"):
        top10_data = st.session_state["margin_top10"]

        st.divider()

        # 요약 대시보드
        m1, m2, m3, m4 = st.columns(4)
        profits = [d["estimated_profit"] for d in top10_data]
        rates = [d["margin_rate"] for d in top10_data]
        positive = [p for p in profits if p > 0]
        m1.metric("분석 상품", f"{len(top10_data)}개")
        m2.metric("최고 마진", f"₩{max(profits):,}" if profits else "₩0")
        m3.metric("평균 마진율", f"{sum(rates)/len(rates):.1f}%" if rates else "0%")
        m4.metric("수익 가능", f"{len(positive)}개", delta=f"{len(positive)}/{len(top10_data)}")

        st.markdown("##### 🏆 마진 TOP 10 — 인터랙티브 분석표")
        st.caption("'시장 최저가' 셀을 더블클릭하여 수정하면 마진이 자동 재계산됩니다")
        st.info("📐 **마진 공식**: 예상마진 = (시장최저가 × 0.9) − (도매가 + 3,000)  |  마진율 = 예상마진 ÷ 시장최저가 × 100  |  0.9 = 수수료 10% 차감, 3,000 = 배송비")

        edit_df = pd.DataFrame(top10_data)

        # 계산 과정 컬럼 추가
        edit_df["calc_detail"] = edit_df.apply(
            lambda r: f"({r['market_lowest']:,} × 0.9) − ({r['cost_price']:,} + 3,000) = {r['estimated_profit']:,}원",
            axis=1,
        )

        edited = st.data_editor(
            edit_df[["title", "cost_price", "market_lowest", "estimated_profit", "margin_rate", "calc_detail", "ai_summary"]],
            use_container_width=True,
            hide_index=True,
            disabled=["title", "cost_price", "estimated_profit", "margin_rate", "calc_detail", "ai_summary"],
            column_config={
                "title": st.column_config.TextColumn("상품명", width="large"),
                "cost_price": st.column_config.NumberColumn("도매가", format="₩%d"),
                "market_lowest": st.column_config.NumberColumn("📝 시장 최저가", format="₩%d"),
                "estimated_profit": st.column_config.NumberColumn("⭐ 예상 마진", format="₩%d"),
                "margin_rate": st.column_config.NumberColumn("마진율", format="%.1f%%"),
                "calc_detail": st.column_config.TextColumn("계산 과정", width="large"),
                "ai_summary": st.column_config.TextColumn("AI 분석", width="large"),
            },
            key="margin_editor",
        )

        # 시장가 수정 시 재계산 표시
        from services.analyzer_service import calc_margin_profit
        if not edited["market_lowest"].equals(pd.DataFrame(top10_data)["market_lowest"]):
            recalc = edited.copy()
            recalc["estimated_profit"] = recalc.apply(
                lambda r: calc_margin_profit(r["cost_price"], r["market_lowest"]), axis=1,
            )
            recalc["margin_rate"] = recalc.apply(
                lambda r: round(r["estimated_profit"] / r["market_lowest"] * 100, 1)
                if r["market_lowest"] > 0 else 0, axis=1,
            )
            st.markdown("##### 📝 수정 반영 결과")
            st.dataframe(
                recalc[["title", "cost_price", "market_lowest", "estimated_profit", "margin_rate"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "title": st.column_config.TextColumn("상품명", width="large"),
                    "cost_price": st.column_config.NumberColumn("도매가", format="₩%d"),
                    "market_lowest": st.column_config.NumberColumn("시장 최저가", format="₩%d"),
                    "estimated_profit": st.column_config.NumberColumn("⭐ 예상 마진", format="₩%d"),
                    "margin_rate": st.column_config.NumberColumn("마진율", format="%.1f%%"),
                },
            )

        # 선택 저장 기능
        st.divider()
        st.markdown("##### 상세 카드 — 체크하고 저장")
        selected_items = []
        for rank, item in enumerate(top10_data, 1):
            with st.container():
                c0, c1, c2, c3 = st.columns([0.3, 1, 3, 2])
                with c0:
                    checked = st.checkbox("", key=f"sel_{item['source']}_{item['item_no']}", label_visibility="collapsed")
                    if checked:
                        selected_items.append(item)
                with c1:
                    if item["image"]:
                        st.image(item["image"], width=100)
                    else:
                        st.markdown("📦")
                    badge = "🟦" if item["source"] == "DOMEME" else "🟧"
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
                    st.caption(f"{medal} {badge}")

                with c2:
                    st.markdown(f"**{item['title'][:60]}**")
                    color = "green" if item["estimated_profit"] > 0 else "red"
                    st.markdown(
                        f"도매가 **{item['cost_price']:,}원** → "
                        f"시장가 **{item['market_lowest']:,}원** | "
                        f":{color}[⭐ **{item['estimated_profit']:,}원** ({item['margin_rate']}%)]"
                    )

                with c3:
                    if item.get("ai_summary") and item["ai_summary"] != "-":
                        st.caption(f"🤖 {item['ai_summary'][:120]}")

                st.divider()

        # 선택 상품 저장 버튼
        save_cols = st.columns([1, 2, 1])
        with save_cols[0]:
            st.caption(f"선택: {len(selected_items)}개")
        with save_cols[1]:
            save_selected = st.button(
                "💾 선택 상품 DB 저장", type="primary", use_container_width=True,
                disabled=len(selected_items) == 0,
            )
        with save_cols[2]:
            save_all = st.button("💾 전체 저장", use_container_width=True)

        items_to_save = top10_data if save_all else (selected_items if save_selected else [])
        if items_to_save:
            saved, skipped = 0, 0

            # AI 스토어상품명 자동 생성
            from services.ai_service import refine_title
            with st.status(f"저장 중... ({len(items_to_save)}개)", expanded=True) as save_status:
                st.write("AI 스토어상품명 생성 중...")
                refined_map = {}
                for i, item in enumerate(items_to_save):
                    st.write(f"  ({i+1}/{len(items_to_save)}) {item['title'][:30]}...")
                    refined_map[item["item_no"]] = _run_async(refine_title(item["title"]))

                st.write("DB 저장 중...")
                with Session() as db:
                    for item in items_to_save:
                        refined = refined_map.get(item["item_no"], item["title"])
                        exists = db.execute(
                            text("SELECT id FROM products WHERE origin_code = :oc"),
                            {"oc": item["item_no"]},
                        ).fetchone()
                        if exists:
                            db.execute(
                                text(
                                    "UPDATE products SET market_lowest_price = :mlp, "
                                    "estimated_margin = :em, selling_point = :sp, "
                                    "refined_title = COALESCE(NULLIF(refined_title, ''), :rt), "
                                    "category = :cat, updated_at = NOW() WHERE origin_code = :oc"
                                ),
                                {
                                    "mlp": item["market_lowest"],
                                    "em": item["estimated_profit"],
                                    "sp": item.get("ai_summary") if item.get("ai_summary") != "-" else None,
                                    "rt": refined,
                                    "cat": item.get("category", ""),
                                    "oc": item["item_no"],
                                },
                            )
                            skipped += 1
                        else:
                            from services.analyzer_service import calc_target_price
                            db.execute(
                                text(
                                    "INSERT INTO products (source, origin_code, title, refined_title, cost_price, "
                                    "sale_price, stock, market_lowest_price, estimated_margin, "
                                    "selling_point, category, is_active) "
                                    "VALUES (:src, :oc, :title, :rt, :cost, :sale, 0, :mlp, :em, :sp, :cat, true)"
                                ),
                                {
                                    "src": item["source"],
                                    "oc": item["item_no"],
                                    "title": item["title"],
                                    "rt": refined,
                                    "cost": item["cost_price"],
                                    "sale": calc_target_price(item["cost_price"]),
                                    "mlp": item["market_lowest"],
                                    "em": item["estimated_profit"],
                                    "sp": item.get("ai_summary") if item.get("ai_summary") != "-" else None,
                                    "cat": item.get("category", ""),
                                },
                            )
                            saved += 1
                    db.commit()
                save_status.update(label=f"저장 완료! 신규 {saved}개, 업데이트 {skipped}개", state="complete")
            st.cache_data.clear()

    # ── 마진 분석 없이 추천만 표시 ──
    elif st.session_state.get("sourcing_recs"):
        recs = st.session_state["sourcing_recs"]
        st.divider()

        m1, m2, m3 = st.columns(3)
        m1.metric("추천 상품", f"{len(recs)}개")
        domeme_cnt = len([r for r in recs if r["source"] == "DOMEME"])
        m2.metric("도매꾹", f"{domeme_cnt}개")
        m3.metric("오너클랜", f"{len(recs) - domeme_cnt}개")

        categories = list(dict.fromkeys(r["category"] for r in recs))
        for cat in categories:
            cat_items = [r for r in recs if r["category"] == cat]
            st.markdown(f"### {cat}")
            for i in range(0, len(cat_items), 4):
                row_items = cat_items[i:i + 4]
                cols = st.columns(4)
                for col, item in zip(cols, row_items):
                    with col:
                        if item["image"]:
                            st.image(item["image"], width=140)
                        else:
                            st.markdown("📦")
                        badge = "🟦" if item["source"] == "DOMEME" else "🟧"
                        title_short = item["title"][:35] + ("..." if len(item["title"]) > 35 else "")
                        st.markdown(f"{badge} **{title_short}**")
                        if item["price"] > 0:
                            st.markdown(f"💰 **{item['price']:,}원**")
                        else:
                            st.caption("가격 미확인")
                        if st.button("📥", key=f"recs_{item['source']}_{item['item_no']}",
                                     help=f"{item['source']} {item['item_no']} 수집"):
                            result = _crawl_product(item["source"], item["item_no"])
                            if result:
                                st.toast(f"수집 완료: {item['title'][:30]}", icon="✅")
                                st.cache_data.clear()
                            else:
                                st.toast("수집 실패", icon="❌")
            st.divider()


# ══════════════════════════════════════════════════════
# 탭 2: 내 상품 관리
# ══════════════════════════════════════════════════════
with tab_products:
    df = load_products(source_filter)

    if df.empty:
        st.info("수집된 상품이 없습니다. '소싱 & 마진 분석' 탭이나 사이드바에서 상품을 수집해 보세요.")
    else:
        # 요약 대시보드
        from services.analyzer_service import calc_target_price, calc_margin_profit

        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("전체 상품", f"{len(df)}개")
        p2.metric("🟦 도매꾹", f"{len(df[df['source'] == 'DOMEME'])}개")
        p3.metric("🟧 오너클랜", f"{len(df[df['source'] == 'OWNERCLAN'])}개")
        p4.metric("판매 중", f"{len(df[df['is_active'] == True])}개")
        avg_cost = df["cost_price"].mean()
        p5.metric("평균 원가", f"₩{avg_cost:,.0f}" if not pd.isna(avg_cost) else "₩0")

        st.divider()

        # 인라인 편집 가능한 데이터 에디터
        st.markdown("##### 상품 목록 — 더블클릭으로 편집 가능")
        st.caption("'스토어상품명', '판매가', '카테고리'를 수정한 뒤 '변경사항 저장' 버튼을 눌러주세요")

        for col in ["market_lowest_price", "estimated_margin"]:
            if col not in df.columns:
                df[col] = 0
            df[col] = df[col].fillna(0)
        for col in ["refined_title", "category", "selling_point"]:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("")

        edit_cols = ["id", "source", "origin_code", "title", "refined_title",
                     "cost_price", "sale_price", "market_lowest_price", "estimated_margin",
                     "category", "selling_point", "stock", "is_active"]
        edit_data = df[edit_cols].copy()

        edited_products = st.data_editor(
            edit_data,
            use_container_width=True,
            hide_index=True,
            disabled=["id", "source", "origin_code", "title", "cost_price",
                       "market_lowest_price", "estimated_margin", "selling_point"],
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "source": st.column_config.TextColumn("도매처", width="small"),
                "origin_code": st.column_config.TextColumn("코드", width="small"),
                "title": st.column_config.TextColumn("원본 제목", width="large"),
                "refined_title": st.column_config.TextColumn("📝 스토어상품명", width="large"),
                "cost_price": st.column_config.NumberColumn("도매가", format="₩%d"),
                "sale_price": st.column_config.NumberColumn("📝 판매가", format="₩%d"),
                "market_lowest_price": st.column_config.NumberColumn("시장 최저가", format="₩%d"),
                "estimated_margin": st.column_config.NumberColumn("예상 마진", format="₩%d"),
                "category": st.column_config.TextColumn("📝 카테고리"),
                "selling_point": st.column_config.TextColumn("AI 소구점", width="large"),
                "stock": st.column_config.NumberColumn("재고"),
                "is_active": st.column_config.CheckboxColumn("판매중"),
            },
            key="product_editor",
        )

        # 변경 감지: session_state에서 실제 편집 내역 확인
        editor_state = st.session_state.get("product_editor", {})
        edited_rows = editor_state.get("edited_rows", {})
        has_pending = len(edited_rows) > 0

        if has_pending:
            st.info(f"📝 {len(edited_rows)}개 행이 수정되었습니다. 아래 버튼을 눌러 저장하세요.")

        save_col, _ = st.columns([1, 2])
        with save_col:
            if st.button("💾 변경사항 저장", type="primary", use_container_width=True, disabled=not has_pending):
                changed = 0
                with Session() as db:
                    for row_idx_str, changes in edited_rows.items():
                        row_idx = int(row_idx_str)
                        orig_row = edit_data.iloc[row_idx]
                        product_id = int(orig_row["id"])

                        rt = changes.get("refined_title", orig_row["refined_title"])
                        sp = changes.get("sale_price", orig_row["sale_price"])
                        cat = changes.get("category", orig_row["category"])
                        ia = changes.get("is_active", orig_row["is_active"])

                        rt = rt if pd.notna(rt) and rt != "" else None
                        cat = cat if pd.notna(cat) and cat != "" else None

                        db.execute(
                            text(
                                "UPDATE products SET refined_title = :rt, sale_price = :sp, "
                                "category = :cat, is_active = :ia, updated_at = NOW() WHERE id = :id"
                            ),
                            {
                                "rt": rt,
                                "sp": float(sp),
                                "cat": cat,
                                "ia": bool(ia),
                                "id": product_id,
                            },
                        )
                        changed += 1
                    db.commit()
                st.toast(f"{changed}개 상품 저장 완료", icon="✅")
                st.cache_data.clear()
                st.rerun()

        btn_c2, btn_c3 = st.columns(2)
        with btn_c2:
            # 판매중 해제된 상품 바로 삭제 (data_editor에서 체크 해제한 것)
            unchecked_ids = []
            for idx, row in edited_products.iterrows():
                if not row["is_active"]:
                    unchecked_ids.append(int(row["id"]))
            if st.button(
                f"🗑️ 체크 해제 상품 삭제 ({len(unchecked_ids)}개)",
                use_container_width=True,
                disabled=len(unchecked_ids) == 0,
            ):
                with Session() as db:
                    for pid in unchecked_ids:
                        db.execute(text("DELETE FROM products WHERE id = :id"), {"id": pid})
                    db.commit()
                st.toast(f"{len(unchecked_ids)}개 상품 삭제 완료", icon="🗑️")
                st.cache_data.clear()
                st.rerun()

        with btn_c3:
            if st.button("🗑️ 전체 삭제", use_container_width=True):
                st.session_state["confirm_delete_all"] = True

            if st.session_state.get("confirm_delete_all"):
                st.warning("정말 전체 삭제하시겠습니까?")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("예, 전체 삭제", type="primary", key="confirm_yes"):
                        with Session() as db:
                            result = db.execute(text("DELETE FROM products"))
                            db.commit()
                        st.toast(f"{result.rowcount}개 전체 삭제 완료", icon="🗑️")
                        st.session_state.pop("confirm_delete_all", None)
                        st.cache_data.clear()
                        st.rerun()
                with cc2:
                    if st.button("취소", key="confirm_no"):
                        st.session_state.pop("confirm_delete_all", None)
                        st.rerun()

        # 가격 모니터링
        st.divider()
        st.markdown("##### 📊 가격 모니터링")
        mon_c1, mon_c2, mon_c3 = st.columns([2, 1, 1])
        with mon_c1:
            scan_target = st.selectbox(
                "개별 조회",
                ["-- 선택 --"] + list(df["title"].values),
                key="scan_target",
            )
        with mon_c2:
            st.write("")
            st.write("")
            scan_btn = st.button("🔍 개별 조회", type="primary")
        with mon_c3:
            st.write("")
            st.write("")
            refresh_all_btn = st.button("🔄 전체 갱신", use_container_width=True)

        # 개별 조회
        if scan_btn and scan_target != "-- 선택 --":
            from services.analyzer_service import get_market_lowest_price, calc_margin_profit
            with st.status(f"'{scan_target[:25]}...' 조회 중...", expanded=True) as status:
                st.write("네이버 검색 중...")
                market_price = _run_async(get_market_lowest_price(scan_target))

                if market_price > 0:
                    row_match = df[df["title"] == scan_target].iloc[0]
                    old_price = int(row_match["market_lowest_price"] or 0)
                    margin = calc_margin_profit(float(row_match["cost_price"]), market_price)
                    with Session() as db_sess:
                        db_sess.execute(
                            text(
                                "UPDATE products SET market_lowest_price = :mlp, "
                                "estimated_margin = :margin, updated_at = NOW() WHERE id = :id"
                            ),
                            {"mlp": market_price, "margin": margin, "id": int(row_match["id"])},
                        )
                        db_sess.commit()
                    change_text = ""
                    if old_price > 0 and market_price != old_price:
                        pct = round((market_price - old_price) / old_price * 100, 1)
                        arrow = "📈" if pct > 0 else "📉"
                        change_text = f" | {arrow} {pct:+.1f}% ({old_price:,} → {market_price:,})"
                    st.write(f"✅ 시장 최저가: **{market_price:,}원** | 수익: **{margin:,.0f}원**{change_text}")
                    st.cache_data.clear()
                    status.update(label="조회 완료!", state="complete")
                else:
                    st.write("❌ 가격을 찾을 수 없습니다.")
                    status.update(label="조회 실패", state="error")

        # 전체 갱신
        if refresh_all_btn:
            from services.price_monitor_service import refresh_market_prices
            active_count = len(df[df["is_active"] == True])
            if active_count == 0:
                st.warning("갱신할 활성 상품이 없습니다.")
            else:
                with st.status(f"전체 {active_count}개 상품 시장가 갱신 중...", expanded=True) as status:
                    progress = st.progress(0)

                    def monitor_cb(cur, total, title=""):
                        progress.progress(cur / total, text=f"({cur}/{total}) {title}")

                    with Session() as db_sess:
                        changes = _run_async(refresh_market_prices(db_sess, monitor_cb))
                    progress.empty()

                    st.write(f"✅ {active_count}개 상품 시장가 갱신 완료")

                    if changes:
                        st.write(f"📊 **{len(changes)}개 가격 변동 감지:**")
                        for c in changes:
                            arrow = "📈" if c.change_pct > 0 else "📉"
                            color = "red" if c.change_pct > 0 else "green"
                            st.markdown(
                                f"- {arrow} **{c.title[:40]}** — "
                                f":{color}[{c.old_price:,} → {c.new_price:,}원 ({c.change_pct:+.1f}%)] | "
                                f"마진: {c.old_margin:,} → {c.new_margin:,}원"
                            )
                        # 세션에 변동 기록 저장
                        st.session_state["price_changes"] = [
                            {"title": c.title, "old": c.old_price, "new": c.new_price,
                             "pct": c.change_pct, "margin": c.new_margin}
                            for c in changes
                        ]
                    else:
                        st.write("가격 변동 없음")

                    status.update(label=f"갱신 완료! ({len(changes)}개 변동)", state="complete")
                st.cache_data.clear()

        # 이전 변동 기록 표시
        if st.session_state.get("price_changes"):
            with st.expander(f"📊 최근 가격 변동 ({len(st.session_state['price_changes'])}건)", expanded=False):
                change_df = pd.DataFrame(st.session_state["price_changes"])
                change_df.columns = ["상품명", "이전가", "현재가", "변동률(%)", "현재마진"]
                st.dataframe(change_df, use_container_width=True, hide_index=True)

        # AI 분석
        st.divider()
        st.markdown("##### 🤖 AI 가격 경쟁력 분석")
        if st.button("AI 분석 실행", key="ai_analyze"):
            analyzed = df[df.get("market_lowest_price", pd.Series(dtype=float)).fillna(0) > 0] if "market_lowest_price" in df.columns else pd.DataFrame()
            if analyzed.empty:
                st.warning("시장 최저가가 조회된 상품이 없습니다. 먼저 최저가를 조회해 주세요.")
            else:
                ai_data = [
                    {
                        "title": r["title"],
                        "cost_price": float(r["cost_price"]),
                        "our_sale_price": float(calc_target_price(float(r["cost_price"]))),
                        "market_lowest_price": float(r["market_lowest_price"]),
                        "estimated_margin": calc_margin_profit(float(r["cost_price"]), float(r["market_lowest_price"])),
                    }
                    for _, r in analyzed.iterrows()
                ]
                from services.ai_service import analyze_price_competitiveness
                with st.status("AI 분석 중...", expanded=True) as status:
                    st.write("Gemini API 호출 중...")
                    ai_result = _run_async(analyze_price_competitiveness(ai_data))
                    status.update(label="AI 분석 완료!", state="complete")
                st.markdown(ai_result)


# ══════════════════════════════════════════════════════
# 탭 3: 마켓 등록 대기열
# ══════════════════════════════════════════════════════
with tab_register:
    reg_df = load_products("ALL")

    if reg_df.empty:
        st.info("등록할 상품이 없습니다. 먼저 상품을 수집해 주세요.")
    else:
        active = reg_df[reg_df["is_active"] == True]
        with_title = active[active["refined_title"].notna() & (active["refined_title"] != "")]

        # 연동 상태 표시
        from services.upload_service import get_upload_service
        _uploader = get_upload_service()
        _status = _uploader.status_summary()

        # 요약 대시보드
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("전체 상품", f"{len(reg_df)}개")
        r2.metric("등록 대기", f"{len(with_title)}개")
        cp_color = "normal" if _status["coupang"] == "Live" else "off"
        r3.metric("쿠팡", _status["coupang"], delta="API 연동" if _status["coupang"] == "Live" else "테스트 모드", delta_color=cp_color)
        ss_color = "normal" if _status["smartstore"] == "Live" else "off"
        r4.metric("스마트스토어", _status["smartstore"], delta="API 연동" if _status["smartstore"] == "Live" else "테스트 모드", delta_color=ss_color)

        # 등록 이력 카운트
        with Session() as _db:
            _reg_count = _db.execute(
                text("SELECT COUNT(*) FROM product_registrations WHERE status = 'REGISTERED'")
            ).scalar() or 0
        r5.metric("등록 완료", f"{_reg_count}개")

        st.divider()

        if with_title.empty:
            st.warning("'스토어상품명'이 없는 상품입니다. 상품 저장 시 AI가 자동 생성하거나, '내 상품 관리' 탭에서 직접 수정하세요.")
        else:
            # ── 일괄 등록 ──
            st.markdown("##### 일괄 등록")
            batch_cols = st.columns([1, 1, 1, 1])
            with batch_cols[0]:
                batch_platform = st.selectbox(
                    "등록 플랫폼",
                    ["coupang", "smartstore"],
                    format_func=lambda x: {"coupang": "🛒 쿠팡", "smartstore": "🟩 스마트스토어"}.get(x, x),
                    key="batch_platform",
                )
            with batch_cols[1]:
                st.write("")
                st.write("")
                batch_all_btn = st.button(
                    f"전체 등록 ({len(with_title)}개)",
                    type="primary", use_container_width=True,
                )

            if batch_all_btn:
                with st.status(f"전체 {len(with_title)}개 상품 {batch_platform} 등록 중...", expanded=True) as status:
                    progress = st.progress(0)
                    success_cnt, fail_cnt = 0, 0

                    with Session() as db_sess:
                        for idx, (_, row) in enumerate(with_title.iterrows()):
                            progress.progress((idx + 1) / len(with_title), text=f"({idx+1}/{len(with_title)}) {row['refined_title'][:25]}")
                            st.write(f"등록 중: {row['refined_title'][:40]}...")

                            product_data = {
                                "title": row["refined_title"],
                                "cost_price": float(row["cost_price"]),
                                "sale_price": float(row["sale_price"]),
                                "category": row.get("category", "") or "",
                                "description": row.get("selling_point", "") or "",
                                "image_url": "",
                                "stock": int(row.get("stock", 0)),
                            }
                            result = _run_async(
                                _uploader.register(batch_platform, product_data, db_sess, int(row["id"]))
                            )
                            if result["status"] == "success":
                                success_cnt += 1
                                st.write(f"  > {result.get('platform_product_id', '')} 등록 완료")
                            else:
                                fail_cnt += 1
                                st.write(f"  > 실패: {result.get('message', '')}")

                    progress.empty()
                    status.update(label=f"등록 완료! (성공 {success_cnt} / 실패 {fail_cnt})", state="complete")
                st.cache_data.clear()

            st.divider()

            # ── 개별 등록 카드 ──
            st.markdown("##### 등록 대기 상품")
            st.caption("스토어상품명이 있는 상품만 표시됩니다.")

            for _, row in with_title.iterrows():
                with st.container():
                    rc1, rc2, rc3 = st.columns([4, 1, 1])
                    with rc1:
                        badge = "🟦" if row["source"] == "DOMEME" else "🟧"
                        st.markdown(
                            f"{badge} **#{row['id']}** `{row['origin_code']}` — "
                            f"**{row['refined_title']}**"
                        )
                        margin_txt = ""
                        if "estimated_margin" in row and float(row.get("estimated_margin") or 0) > 0:
                            margin_txt = f" · 마진 {float(row['estimated_margin']):,.0f}원"
                        st.caption(
                            f"원가 {row['cost_price']:,.0f}원 · "
                            f"판매가 {row['sale_price']:,.0f}원 · "
                            f"재고 {row['stock']}개{margin_txt}"
                        )
                        # 기존 등록 이력 표시
                        with Session() as _db:
                            _regs = _db.execute(
                                text(
                                    "SELECT platform, status, platform_product_id, registered_at "
                                    "FROM product_registrations WHERE product_id = :pid ORDER BY created_at DESC"
                                ),
                                {"pid": int(row["id"])},
                            ).fetchall()
                        if _regs:
                            reg_badges = []
                            for rr in _regs:
                                p_icon = "🛒" if rr[0] == "COUPANG" else "🟩"
                                s_icon = {"REGISTERED": "✅", "FAILED": "❌", "PENDING": "⏳", "DELETED": "🗑️"}.get(rr[1], "")
                                reg_badges.append(f"{p_icon}{s_icon} `{rr[2] or ''}`")
                            st.caption("등록: " + " | ".join(reg_badges))

                    with rc2:
                        if st.button("🛒 쿠팡", key=f"reg_cp_{row['id']}", use_container_width=True):
                            product_data = {
                                "title": row["refined_title"],
                                "cost_price": float(row["cost_price"]),
                                "sale_price": float(row["sale_price"]),
                                "category": row.get("category", "") or "",
                                "description": row.get("selling_point", "") or "",
                                "image_url": "",
                                "stock": int(row.get("stock", 0)),
                            }
                            with Session() as db_sess:
                                result = _run_async(
                                    _uploader.register("coupang", product_data, db_sess, int(row["id"]))
                                )
                            if result["status"] == "success":
                                st.toast(f"쿠팡 등록 완료: {result.get('platform_product_id', '')}", icon="🛒")
                            else:
                                st.toast(f"쿠팡 등록 실패: {result.get('message', '')}", icon="❌")
                            st.cache_data.clear()
                            st.rerun()

                    with rc3:
                        if st.button("🟩 네이버", key=f"reg_nv_{row['id']}", use_container_width=True):
                            product_data = {
                                "title": row["refined_title"],
                                "cost_price": float(row["cost_price"]),
                                "sale_price": float(row["sale_price"]),
                                "category": row.get("category", "") or "",
                                "description": row.get("selling_point", "") or "",
                                "image_url": "",
                                "stock": int(row.get("stock", 0)),
                            }
                            with Session() as db_sess:
                                result = _run_async(
                                    _uploader.register("smartstore", product_data, db_sess, int(row["id"]))
                                )
                            if result["status"] == "success":
                                st.toast(f"스마트스토어 등록 완료: {result.get('platform_product_id', '')}", icon="🟩")
                            else:
                                st.toast(f"스마트스토어 등록 실패: {result.get('message', '')}", icon="❌")
                            st.cache_data.clear()
                            st.rerun()

                    st.divider()

        # ── 등록 이력 ──
        st.markdown("##### 등록 이력")
        with Session() as _db:
            _history = _db.execute(
                text(
                    "SELECT r.id, r.platform, r.status, r.platform_product_id, "
                    "r.platform_url, r.error_message, r.registered_at, "
                    "COALESCE(NULLIF(p.refined_title, ''), p.title) as display_title "
                    "FROM product_registrations r "
                    "JOIN products p ON r.product_id = p.id "
                    "ORDER BY r.created_at DESC LIMIT 50"
                )
            ).fetchall()

        if _history:
            for h in _history:
                reg_id, platform, status, platform_pid, platform_url, error_msg, reg_at, display_title = h
                p_icon = "🛒 쿠팡" if platform == "COUPANG" else "🟩 네이버"
                s_map = {"REGISTERED": "✅ 등록", "FAILED": "❌ 실패", "PENDING": "⏳ 대기", "DELETED": "🗑️ 삭제"}

                hc1, hc2, hc3 = st.columns([5, 1, 1])
                with hc1:
                    reg_date = str(reg_at)[:19] if reg_at else ""
                    st.markdown(
                        f"{p_icon} {s_map.get(status, status)} · "
                        f"**{(display_title or '')[:40]}** · "
                        f"`{platform_pid or ''}` · {reg_date}"
                    )
                    if error_msg:
                        st.caption(f"⚠️ {error_msg}")
                with hc2:
                    if platform_url:
                        st.link_button("🔗 보기", platform_url, use_container_width=True)
                with hc3:
                    if status == "REGISTERED" and platform_pid:
                        if st.button("🗑️ 삭제", key=f"del_reg_{reg_id}", use_container_width=True):
                            plat_key = "coupang" if platform == "COUPANG" else "smartstore"
                            with Session() as del_db:
                                del_result = _run_async(
                                    _uploader.delete(plat_key, platform_pid, del_db, reg_id)
                                )
                            if del_result["status"] == "success":
                                st.toast(f"{p_icon} 상품 삭제 완료", icon="🗑️")
                            else:
                                st.toast(f"삭제 실패: {del_result.get('message', '')}", icon="❌")
                            st.cache_data.clear()
                            st.rerun()
        else:
            st.caption("등록 이력이 없습니다.")
