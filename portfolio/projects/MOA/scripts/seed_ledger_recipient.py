"""계정별원장 지사 담당자 시드 — 지사 명단표(2026-08-24 사진)에서 옮겨 적는다.

지사 이름과 계정 코드 짝은 scripts/seed_account_opening.py 와 같다. 명단표에는
'경남지사'·'대전지사'로 적혀 있지만 계정은 각각 1410010 경남중앙지사,
1410016 대전세종지사다.

**메일 주소는 아직 비어 있다.** EMAIL 이 빈 담당자는 넣지 않고 넘어가며, 끝에
몇 명이 빠졌는지 찍는다 — 조용히 반만 들어가면 그 지사만 안 나간다.

재실행해도 안전하다(upsert). 표에서 뺀 사람은 지우지 않고 active='N' 이 된다.

    python -m scripts.seed_ledger_recipient
"""

from app.database import get_session_factory
from app.services.ledger_mail import save_recipients

# (계정, 지사 이름, 담당자, 메일 주소)
# 담당자는 명단표에서 읽은 그대로다. 수기로 덧붙인 칸은 뒤에 (수기)로 적어 둔다.
RECIPIENTS = [
    ("1410002", "경기지사",     "지인자", ""),
    ("1410003", "경인지사",     "함소담", ""),   # 수기
    ("1410004", "북부지사",     "손민경", ""),
    ("1410005", "강원지사",     "임혜련", ""),
    ("1410006", "충청지사",     "최은해", ""),
    ("1410018", "충남지사",     "이미희", ""),
    ("1410008", "대구지사",     "김은희", ""),
    ("1410009", "부산지사",     "이연주", ""),
    ("1410010", "경남중앙지사", "진지영", ""),
    ("1410011", "호남지사",     "이은정", ""),   # 수기
    ("1410013", "제주지사",     "박지혜", ""),
    ("1410022", "동부지사",     "유현준", ""),
    ("1410015", "전북지사",     "박민주", ""),
    ("1410016", "대전세종지사", "김새봄", ""),
    ("1410019", "울산지사",     "유현아", ""),   # 수기
    ("1410020", "경북지사",     "박소희", ""),   # 수기
    ("1410021", "경기서부지사", "김수빈", ""),   # 수기
]


def main() -> None:
    db = get_session_factory()()
    missing: list[str] = []
    try:
        for code, office, name, email in RECIPIENTS:
            if not email:
                missing.append(f"{code} {office} {name}")
                continue
            save_recipients(db, code, [{"name": name, "email": email, "kind": "TO"}])
            print(f"  {code} {office:14s} {name:5s} {email}")
    finally:
        db.close()

    done = len(RECIPIENTS) - len(missing)
    print(f"\n담당자 {done}/{len(RECIPIENTS)}명 저장 완료")
    if missing:
        print(f"\n메일 주소가 없어 넣지 못한 {len(missing)}명 — 이 지사는 발송되지 않는다:")
        for line in missing:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
