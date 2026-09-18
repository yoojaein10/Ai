"""'화면 슬롯 하나' 담보 폼 자동입력의 공통 몸통 — 수협·하나·우리·새마을(autofill_ssb/hnb/wrb/mgb 가 쓴다).

농협(autofill_nh)과 같은 계약: 폼은 물건 하나를 보여 주고 `일련번호`(앵커)로 물건을 넘긴다. 화면이
보고 있는 물건이 우리 몇 번째인지 은행별 `verify_fill_<bank>.seq_alignment` 로 정합하고, **그 슬롯 하나만**
채운다. 다물건 슬롯 넘김은 자동화하지 않는다(인계본 `--all --live` 는 감사 P0-C 로 봉인돼 있었다) —
러너가 `LAST_ALIGN["total"] >= 2` 를 보고 비고 '다물건 일부만 입력' 을 남긴다.

기본은 **드라이런**(계획만, 화면 안 건드림). 실입력은 `--live` 로만. 저장은 여기서 하지 않는다.
종료코드: 0 정상 · 1 거부 칸 있음(채우긴 함) · 2 다물건 정합 불명확(아무것도 안 채움) ·
          4 미지원 물건(선박·어업권·집계형 등 — 아무것도 안 채움). 2·4 는 러너가 저장 없이 실패로 끝낸다(fail-closed).
콤보는 이 계통의 `form.fill`(recon 콤보 목록 + 되읽기 검증, 목록에 없는 값은 타이핑 전 거부)이 고른다 —
인계본이 봉인했던 `--select`(닫힌 드롭다운 ENTER→저장 커밋 위험) 경로는 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.ui import driver, form              # noqa: E402
from pywinauto.keyboard import send_keys      # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

EXIT_REJECTED = 1
EXIT_UNALIGNED = 2        # 다물건 정합 불명확 — 실입력 건너뜀(아무것도 안 채움)
EXIT_UNSUPPORTED = 4      # 미지원 물건(선박·어업권·집계형 등) — 실입력 건너뜀(아무것도 안 채움)
ORDER = {"거부": 0, "덮어씀": 1, "선택(덮어씀)": 1, "미발견": 2, "채움": 3, "선택": 3, "수동(선택형)": 4, "일치": 5, "빈값": 6}


@dataclass
class Spec:
    bank: str                 # 보고서 이름(수협/하나/우리/새마을)
    form_class: str           # 담보 폼 클래스(TBNK…24DAMB)
    mapping: object           # bankon.mapping.<bank> (build(ctx, seq))
    verify: object            # verify_fill_<bank> (seq_alignment · guard_reasons · COMBO_LISTS)
    kind_field: str           # 물건 유형 칸 이름(요약 표시용)
    last_align: dict = field(default_factory=dict)   # 마지막 실행의 다물건 정합 정보(러너가 요약에 쓴다)


def _report(results, totals):
    for r in sorted(results, key=lambda x: (ORDER.get(x.action.split("(")[0] if x.action.startswith("거부") else x.action, 9), x.label)):
        if r.action == "빈값":
            continue
        mark = "✍" + ("완료" if r.wrote else "") if r.action in ("채움", "덮어씀", "선택", "선택(덮어씀)") else r.action
        name = form.display_label(r.label)
        print(f"  [{mark:9}] {name[:18]:20} 넣을값={r.ours[:24]:26} 현재={r.current[:20]}")
    totals["채움"] += sum(1 for x in results if x.action in ("채움", "덮어씀", "선택", "선택(덮어씀)"))
    totals["일치"] += sum(1 for x in results if x.action == "일치")
    totals["수동"] += sum(1 for x in results if x.action == "수동(선택형)")
    totals["미발견"] += sum(1 for x in results if x.action == "미발견")
    totals["거부"] += sum(1 for x in results if x.action.startswith("거부"))
    totals["완료"] += sum(1 for x in results if x.wrote)


# ── 다물건: 화면 물건 행을 늘려 **전 물건**을 채운다(사용자 결정 2026-09-16) ──────────────────
# 종전엔 화면이 보고 있는 슬롯 하나만 채우고 비고에 '나머지 수동' 을 남겼다. 2871(하나, 잠실동)
# 실측: 명세가 토지 1 + 건물 단가별 3 인데 토지만 들어가 담당자가 4행을 손으로 만들어 채웠다.
# 하나·수협·우리·새마을 네 폼 모두 **숫자 물건순번 칸**이 있어(하나·수협·우리 '일련번호',
# 새마을 '물건일련번호') 행 위치를 확인할 수 있다 — 그걸 앵커로 Ctrl+Home→↓ 로 행을 옮긴다.
_SLOT_KEYS = ("물건일련번호", "일련번호", "일련번호_0", "일련번호_1", "일련번호_2")
_AMOUNT_KEYS = ("감정평가액", "감정가액")      # 새마을은 '감정가액'
_MAX_ROWS = 30                                 # 폭주 방지(물건 30개 넘으면 사람이)


def _digits(text) -> str:
    return "".join(c for c in str(text or "") if c.isdigit())


def _screen_slot(screen: dict) -> int | None:
    """화면이 보고 있는 물건 행 번호(1부터). BANK24 가 만든 9자리 serial 은 걸러낸다."""
    for key in _SLOT_KEYS:
        text = _digits(screen.get(key))
        if text and len(text) <= 3:
            return int(text)
    return None


def _screen_amount(screen: dict) -> str:
    for key in _AMOUNT_KEYS:
        text = _digits(screen.get(key))
        if text:
            return text
    return ""


def object_grids(form_ref) -> list:
    """폼 안 물건 그리드 후보 — **오른쪽 것부터**.

    ★폼마다 물건 그리드 위치가 다르다: 신한은 왼쪽(navigate._object_grid 관례)이지만
    하나는 TcxGridSite 가 둘이고 **오른쪽**이 물건 그리드다(2871 실측 2026-09-16:
    왼쪽 그리드에선 ↓·Ctrl+End·Shift+F10 이 전부 안 먹었고, 오른쪽에서 순번 1→5 가 움직였다).
    그래서 은행별 상수를 두지 않고, 후보를 훑어 **실제로 순번이 움직이는 그리드**를 쓴다.
    """
    grids = driver.by_class(form_ref.handle, "TcxGridSite")
    return sorted(grids, key=lambda g: g.rectangle().left, reverse=True)


def _count_in(form_ref, grid) -> int | None:
    """이 그리드에서 Ctrl+End 를 눌러 본 뒤 화면 순번(= 행 수). 안 움직이면 1 이 나온다."""
    try:
        grid.set_focus()
    except Exception:                    # noqa: BLE001
        return None
    time.sleep(0.3)
    send_keys("^{END}")
    time.sleep(0.5)
    return _screen_slot(vf.screen_values(form_ref))


def _count_rows(form_ref) -> tuple[int | None, object]:
    """(행 수, 물건 그리드). 후보마다 Ctrl+End 를 눌러 **가장 큰 순번**을 쓴다.

    엉뚱한 그리드는 순번을 못 움직여 1 을 돌려주므로 최대값이 곧 진짜 행 수다 —
    적게 세면 이미 있는 행을 또 추가해 버리니 이쪽으로 fail-safe 하게 잡는다.
    """
    best, best_grid = None, None
    for grid in object_grids(form_ref):
        count = _count_in(form_ref, grid)
        if count is not None and (best is None or count > best):
            best, best_grid = count, grid
    return best, best_grid


def _select_row(form_ref, grid, index: int) -> None:
    """index(0부터)번째 물건 행을 고르고 화면 순번으로 확인한다(어긋나면 예외 — fail-closed)."""
    grid.set_focus()
    time.sleep(0.3)
    send_keys("^{HOME}")
    time.sleep(0.4)
    for _ in range(index):
        send_keys("{DOWN}")
        time.sleep(0.2)
    time.sleep(0.3)
    slot = _screen_slot(vf.screen_values(form_ref))
    if slot != index + 1:
        raise RuntimeError(f"{index + 1}행 선택 실패(화면 순번={slot})")


def _add_rows(form_ref, grid, have: int, need: int) -> tuple[int, object, str | None]:
    """부족한 만큼 **빈 행**을 추가한다. (최종 행 수, 쓸 그리드, 실패사유).

    복사 추가(X)가 아니라 빈 행 추가(U)를 쓴다 — 복사는 앞 물건 값이 그대로 남아 있어
    빈칸만 채우는 원칙(overwrite=False)과 겹치면 **앞 물건 값이 그 행에 남는다**.
    행이 하나뿐인 새 폼에선 어느 그리드가 물건 그리드인지 순번으로 가릴 수 없으므로
    (전부 1), 후보를 차례로 시도해 **행 수가 실제로 늘어난 그리드**를 채택한다.
    """
    count = have
    candidates = [g for g in ([grid] if grid is not None else []) ]
    candidates += [g for g in object_grids(form_ref) if g is not grid]
    last_error: Exception | None = None
    for candidate in candidates:
        while count < need:
            try:
                after = _add_row_on(form_ref, candidate, count)
            except Exception as error:   # noqa: BLE001 — 그리드가 아니면 팝업이 안 열린다
                last_error = error
                break
            count = after
        if count >= need:
            return count, candidate, None
    return count, grid, f"행 추가 실패({last_error or f'행 {count}/{need}'})"


def _add_row_on(form_ref, grid, have: int) -> int:
    """그 그리드의 팝업(Shift+F10 → 'u' 추가(마지막위치))으로 빈 행 하나를 추가한다.

    추가 뒤 행 수가 실제로 늘었는지 확인한다 — 안 늘었으면 그 그리드는 물건 그리드가 아니다.
    폼 상태만 바뀌고 저장은 하지 않는다(러너가 저장을 누른다).
    """
    from bankon.ui import navigate
    grid.set_focus()
    time.sleep(0.3)
    menus = navigate._menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not (navigate._menu_handles() - menus):
        time.sleep(0.1)
    if not (navigate._menu_handles() - menus):
        raise RuntimeError("물건 그리드 팝업이 열리지 않음")
    send_keys(navigate.OBJECT_MENU["append"])
    time.sleep(0.9)
    after = _count_in(form_ref, grid)
    if after is None or after <= have:
        navigate.close_context_menu()
        raise RuntimeError(f"행이 늘지 않음({have}→{after})")
    return after


def run_all_objects(spec: Spec, ctx, form_ref, *, live: bool, overwrite: bool, total: int) -> int:
    """물건 전체를 순번대로 채운다. 화면 행이 모자라면 빈 행을 추가한다(저장은 러너가)."""
    notes: list[str] = []
    have, grid = _count_rows(form_ref)
    if have is None or grid is None:
        spec.last_align["slots"] = "화면 물건순번을 못 읽어 다물건 자동입력 보류 — 슬롯 1만 입력"
        return run_one_slot(spec, ctx, form_ref, live=live, overwrite=overwrite, seq="1")
    if total > _MAX_ROWS:
        spec.last_align["slots"] = f"물건 {total}개(상한 {_MAX_ROWS} 초과) — 자동입력 보류, 담당자 수동"
        return EXIT_UNALIGNED
    rows, grid, failure = _add_rows(form_ref, grid, have, total)
    if failure:
        notes.append(failure)
    print(f"  물건 행: 화면 {have} → {rows} (감정서 물건 {total}개)")

    totals = {"채움": 0, "일치": 0, "수동": 0, "미발견": 0, "거부": 0, "완료": 0}
    filled = 0
    for index in range(min(total, rows)):
        seq = str(index + 1)
        try:
            _select_row(form_ref, grid, index)
        except Exception as error:       # noqa: BLE001
            notes.append(f"{seq}행 선택 실패 — 이후 행 중단({error})")
            break
        values = spec.mapping.build(ctx, seq)
        reasons = spec.verify.guard_reasons(ctx, values, seq)
        if reasons:
            notes.append(f"{seq}행 보류({'; '.join(reasons)})")
            continue
        screen = vf.screen_values(form_ref)
        ours, theirs = _digits(values.get("감정평가액") or values.get("감정가액")), _screen_amount(screen)
        if theirs and ours and theirs != ours:
            notes.append(f"{seq}행 화면 금액 {theirs} ≠ 우리 {ours} — 건드리지 않음")
            continue
        print(f"\n----- {seq}행 ← 물건 {seq}/{total} "
              f"({values.get(spec.kind_field)} {values.get('사정면적')}) -----")
        results = form.fill(form_ref, values, live=live, overwrite=overwrite,
                            combo_lists=spec.verify.COMBO_LISTS)
        _report(results, totals)
        filled += 1

    done = f"물건 {total}개 중 {filled}개 입력"
    spec.last_align["slots"] = done + ((" — " + "; ".join(notes)) if notes else " (전부)")
    label = "입력완료" if live else "채울계획"
    print(f"\n[전체] {done} · {label} {totals['완료'] if live else totals['채움']} · 일치 {totals['일치']} · "
          f"수동 {totals['수동']} · 칸못찾음 {totals['미발견']} · 거부 {totals['거부']}")
    if notes:
        print("  ⚠ " + " / ".join(notes))
    return EXIT_REJECTED if totals["거부"] else 0


def run_one_slot(spec: Spec, ctx, form_ref, *, live: bool, overwrite: bool, seq: str | None) -> int:
    """종전 경로 — 화면이 보고 있는 슬롯 하나만 채운다."""
    values = spec.mapping.build(ctx, seq)
    reasons = spec.verify.guard_reasons(ctx, values, seq)
    spec.last_align["guard"] = "; ".join(reasons)
    if reasons:
        print("  ⚠ 실입력 보류(계획만): " + " / ".join(reasons))
        if live:
            return EXIT_UNSUPPORTED
    totals = {"채움": 0, "일치": 0, "수동": 0, "미발견": 0, "거부": 0, "완료": 0}
    results = form.fill(form_ref, values, live=live, overwrite=overwrite,
                        combo_lists=spec.verify.COMBO_LISTS)
    _report(results, totals)
    label = "입력완료" if live else "채울계획"
    print(f"\n[전체] {label} {totals['완료'] if live else totals['채움']} · 일치 {totals['일치']} · "
          f"수동 {totals['수동']} · 칸못찾음 {totals['미발견']} · 거부 {totals['거부']}")
    return EXIT_REJECTED if totals["거부"] else 0


def run(spec: Spec, argv=None) -> int:
    p = argparse.ArgumentParser(prog=f"autofill_{spec.form_class}")
    p.add_argument("doc_id")
    p.add_argument("--live", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-touch", action="store_true", help="(호환용) 드라이런은 아무것도 안 건드린다")
    p.add_argument("--seq", default=None, help="우리 물건 순번(다물건 정합 건너뜀 · 슬롯 하나만)")
    p.add_argument("--all-objects", action="store_true",
                   help="다물건이면 화면 행을 늘려 전 물건을 순번대로 채운다(러너 기본)")
    p.add_argument("--one-slot", action="store_true",
                   help="종전 동작 — 화면이 보고 있는 슬롯 하나만 채운다")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == spec.form_class]
    if not forms:
        others = [f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)]
        print(f"{spec.bank} 담보 화면({spec.form_class})이 안 열려 있습니다. (열린: {others or '없음'})", file=sys.stderr)
        return 1
    form_ref = forms[0]

    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, args.doc_id)),
                      str(Path("output") / args.doc_id))
    ctx = vf.build_context(cfg, args.doc_id, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form_ref)
    align = spec.verify.seq_alignment(ctx, screen, args.seq)
    spec.last_align.clear()
    spec.last_align.update(align)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = spec.mapping.build(ctx, resolved)
    reasons = spec.verify.guard_reasons(ctx, values, resolved)
    spec.last_align["guard"] = "; ".join(reasons)

    mode = "🔴 실제입력(LIVE)" if args.live else "🟢 드라이런(계획만)"
    print(f"===== {args.doc_id} {spec.bank} 자동입력 — {mode} · {spec.kind_field}={values.get(spec.kind_field)!r} · 물건 {align['total']}개 "
          f"(화면 슬롯 {align.get('screen_seq') or '?'} → 우리 {align['resolved']} · {align['by']}) =====")
    # 다물건: 전 물건 경로(러너 기본). 순번을 직접 준 건(--seq)·--one-slot 은 종전대로 슬롯 하나.
    if args.all_objects and not args.one_slot and not args.seq and align["total"] >= 2:
        return run_all_objects(spec, ctx, form_ref, live=args.live,
                               overwrite=args.overwrite, total=align["total"])
    if align["total"] >= 2 and not align["safe"]:
        print("  ⚠ 다물건 정합이 불명확 — 실입력은 보류(드라이런만).")
        if args.live:
            return EXIT_UNALIGNED      # 아무것도 안 채움 — 러너는 저장 없이 실패로 끝내야 한다
    if align["total"] >= 2:
        spec.last_align["slots"] = (f"물건 {align['total']}개 중 슬롯 "
                                    f"{align.get('screen_seq') or '?'} 하나만 입력 — 나머지 수동")
    return run_one_slot(spec, ctx, form_ref, live=args.live, overwrite=args.overwrite, seq=resolved)
