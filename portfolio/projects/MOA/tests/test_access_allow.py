from scripts.seed_access_allow import ALLOWED


def test_allowlist_has_expected_people_and_no_duplicates():
    names = {name for _, name in ALLOWED}
    seqs = [seq for seq, _ in ALLOWED]
    assert names == {
        "이일우", "유재인", "원동하", "김경희", "장세희", "임정미", "박중현", "고정은"
    }
    assert len(seqs) == len(set(seqs)) == 8  # USR_SEQ 중복 없음
    # 동명이인 확정: 박중현=본사 429, 유재인=재직 1260, 임정미=재직 1060
    mapping = dict((name, seq) for seq, name in ALLOWED)
    assert mapping["박중현"] == 429
    assert mapping["유재인"] == 1260
    assert mapping["임정미"] == 1060
