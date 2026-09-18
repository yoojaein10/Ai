"""탭 껍데기 — 메뉴를 탭으로 띄워 하던 작업이 살아 있게 한다 (2026-08-20 사용자 요청).

화면을 옮기면 이전 페이지가 통째로 사라지던 것을 아마란스10 처럼 바꾼 것이다.
화면 코드라 값을 파이썬으로 검증할 수 없어, 구조가 무너지지 않았는지로 본다.
동작(열기·전환·닫기·내려받기 다리)은 브라우저로 실제 조작해 확인했다.
"""

from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"


def test_껍데기_화면이_탭과_메뉴_자리를_갖춘다():
    html = (UI / "shell.html").read_text(encoding="utf-8")

    assert 'id="shellTabs"' in html, "탭 바가 없으면 화면을 고를 수 없다"
    assert 'id="shellFrames"' in html, "화면을 담을 자리가 없다"
    assert 'class="side-nav"' in html, "context.js 가 메뉴를 그릴 자리가 필요하다"
    assert "/ui/context.js" in html and "/ui/shell.js" in html


def test_껍데기는_메뉴_관문에서_빠진다():
    """/desktop/shell 에 대응하는 메뉴가 없어, 안 빼면 첫 허용 메뉴로 튕긴다."""
    script = (UI / "context.js").read_text(encoding="utf-8")

    assert "const A10_IS_SHELL = location.pathname === '/desktop/shell'" in script
    assert "if(!A10_IS_SHELL && (!currentMenuKey || !window.A10_CAN(currentMenuKey)))" in script


def test_iframe_안에서는_내려받기를_껍데기에_넘긴다():
    """EXE 저장 다리(window.pywebview)는 맨 위 창에만 붙는다.

    이걸 안 넘기면 EXE 에서 엑셀 내보내기·인쇄 파일이 조용히 안 받아진다.
    """
    script = (UI / "context.js").read_text(encoding="utf-8")

    download = script[script.index("window.A10_DOWNLOAD = function"):]
    download = download[:download.index("\n};")]

    assert "if(A10_IN_SHELL)" in download
    assert "postMessage({type:'a10:download', path}, location.origin)" in download
    assert download.index("A10_IN_SHELL") < download.index("window.pywebview"), (
        "pywebview 를 먼저 보면 iframe 안에서 안 잡혀 창이 통째로 이동한다"
    )


def test_껍데기가_남의_창_메시지는_듣지_않는다():
    """iframe 다리는 같은 서버에서 온 것만 받아야 한다."""
    script = (UI / "shell.js").read_text(encoding="utf-8")

    listener = script[script.index("window.addEventListener('message'"):]
    assert "if (event.origin !== location.origin) return;" in listener[:400]
    assert "data.path.startsWith('/')" in listener, "바깥 주소로 내려받기를 시키면 안 된다"


def test_iframe_안에서는_상단바와_사이드바를_감춘다():
    """감추는 규칙은 context.js 가 직접 넣는다 — CSS 파일에만 두면 그 파일이
    캐시된 화면에서 상단바·사이드바가 겹쳐 보인다 (2026-08-20 보수기준 점검
    제보: 그 화면만 ?v 없이 걸려 있어 옛 CSS 를 쓰고 있었다).
    """
    css = (UI / "desktop.css").read_text(encoding="utf-8")
    script = (UI / "context.js").read_text(encoding="utf-8")

    assert ".in-shell .topbar, .in-shell .sidebar{ display: none !important; }" in css
    assert ".in-shell .topbar,.in-shell .sidebar{display:none !important}" in script, (
        "CSS 캐시에 기대면 화면마다 되고 안 되고가 갈린다"
    )


def test_탭은_주소가_아니라_메뉴_이름으로_보인다():
    """2026-08-20 제보 — 탭에 '/desktop/card-vouchers?usr=813' 이 그대로 찍혔다.

    context.js 가 메뉴 링크에 ?usr= 를 붙이는데, 탭이 주소를 그대로 열쇠로 쓰면
    A10_MENU 에서 이름을 못 찾는다. 경로로 다뤄야 이름이 붙고, 사람이 바뀌어도
    지난 탭이 되살아난다.
    """
    script = (UI / "shell.js").read_text(encoding="utf-8")

    assert "const pathOf = href =>" in script, "경로만 떼는 자리가 없다"
    # 이름은 사이드바에 그려진 한글을 그대로 쓴다. context.js 의 A10_MENU 는 const 라
    # window 에 붙지 않아 window.A10_MENU 로는 못 읽는다 — 그렇게 짰다가 탭에 주소가
    # 그대로 찍혔다(2026-08-20). 시험 하네스가 window.A10_MENU 를 만들어 놔서 못 잡았다.
    label = script[script.index("function labelFor(path)"):]
    label = label[:label.index("\n  }")]
    assert ".side-nav a" in label, "사이드바 글자를 안 보면 메뉴명이 안 나온다"
    assert "window.A10_MENU" not in label.split("typeof A10_MENU")[0], (
        "window.A10_MENU 만 보면 늘 undefined 다"
    )
    # 틀은 ?usr= 가 붙은 실제 주소로 열어야 사용자 확인이 통과한다
    assert "frame.src = hrefFor(path);" in script
    assert "restored.map(pathOf)" in script, "지난 탭도 경로로 맞춰야 한다"


def test_desktop_진입이_껍데기다():
    """EXE 는 /desktop 을 연다 — 여기가 껍데기여야 켜자마자 탭이 보인다.

    EXE 자체는 고치지 않는다(재배포 불필요). 감정서 LIST 는 /desktop/dashboard
    로 옮겼다 — /desktop 이 그대로 감정서 LIST 를 가리키면 그 메뉴를 누를 때
    껍데기 안에 껍데기가 열린다.
    """
    main = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    script = (UI / "context.js").read_text(encoding="utf-8")

    desktop = main[main.index('@app.get("/desktop", include_in_schema=False)'):]
    desktop = desktop[:desktop.index("@app.get", 10)]
    assert '"shell.html"' in desktop, "/desktop 이 껍데기를 주지 않는다"

    assert '@app.get("/desktop/dashboard"' in main, "감정서 LIST 로 갈 자리가 없다"
    assert "{ label: '감정서 LIST', href: '/desktop/dashboard' }" in script
    assert "if(url.pathname === '/desktop/dashboard') return 'appraisals';" in script, (
        "메뉴 키가 옛 주소에 붙어 있으면 감정서 LIST 가 권한에서 막힌다"
    )
    # 껍데기는 두 주소 모두 메뉴 관문에서 빠져야 한다
    assert "location.pathname === '/desktop/shell'" in script
    assert "location.pathname === '/desktop'" in script


def test_사이드바가_창을_넘으면_스스로_굴러간다():
    """껍데기는 body 스크롤을 막는다 — 사이드바에 제 스크롤이 없으면 메뉴 아래쪽이
    통째로 잘린다 (2026-08-21 제보: '카드·반제' 밑이 안 보인다).

    실측(창 740px, 묶음 전부 펼침): 메뉴 내용 1079px vs 사이드바 676px.
    고치기 전에는 사이드바가 창 밖 910px 까지 뻗고 스크롤도 안 됐다.
    """
    html = (UI / "shell.html").read_text(encoding="utf-8")

    assert "body{overflow:hidden;display:flex;flex-direction:column;height:100dvh}" in html
    assert ".sidebar{min-height:0;overflow-y:auto" in html, "사이드바에 제 스크롤이 없다"
    assert ".app-shell{flex:1;min-height:0;width:100%}" in html, (
        "width:100% 가 빠지면 margin:0 auto 가 가로 늘이기를 꺼서 본문이 0px 이 된다"
    )
    # 상단바 높이를 손으로 빼면 그 숫자가 어긋날 때 아래가 잘린다 (주석의 설명은 봐준다)
    assert "height:calc(100dvh - 64px)" not in html
