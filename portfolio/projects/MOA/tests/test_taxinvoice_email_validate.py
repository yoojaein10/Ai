"""발급 팝업 이메일 자동 채움 뒤 검증 재실행 (2026-08-28 사용자 보고).

거래처를 고르면(pickCustomer) 이메일 칸을 비우고 담당자탭 이메일을 비동기로
채우는데, renderModeState → validate 는 그 사이 빈 칸을 보고 빨간 테두리를
칠한다. 프로그램이 채운 값은 input 이벤트가 없어 검증이 다시 안 돌아, 멀쩡한
이메일이 채워져 있는데도 빨간 테두리(발급 버튼 잠김)가 남아 다시 쳐야 풀렸다.
"""

from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"


def test_담당자_이메일을_채운_뒤_검증을_다시_돌린다():
    script = (UI / "taxinvoice-dialog.js").read_text(encoding="utf-8")
    block = script[script.index("async function fillContactEmail"):]
    block = block[:block.index("\n  }") + 4]

    fill = block.index("$('taxRcvEmail').value = email;")
    assert "validate();" in block[fill:], (
        "프로그램이 채운 값은 input 이벤트가 없다 — validate 를 직접 불러야 "
        "빨간 테두리와 발급 잠김이 풀린다"
    )
