import pytest

from bankon.sources import archive


def _make(root, year_name="0-2026년 on-line전례"):
    cat = root / year_name / "3-담보"
    (cat / "2501~3000" / "01-2608-3-2676").mkdir(parents=True)
    (cat / "2501~3000" / "01-2608-3-2676" / "01-2608-3-2676.pdf").write_bytes(b"%PDF")
    (cat / "2501~3000" / "01-2608-3-2676" / "의뢰서.pdf").write_bytes(b"%PDF")
    # 꼬리 붙은 폴더 + 정확한 파일명
    (cat / "0001~0500" / "01-2601-3-0008(HUG)").mkdir(parents=True)
    (cat / "0001~0500" / "01-2601-3-0008(HUG)" / "01-2601-3-0008.pdf").write_bytes(b"%PDF")
    # 잘못된 범위 폴더에 들어간 건
    (cat / "2501~3000" / "01-2607-3-2359").mkdir(parents=True)
    (cat / "2501~3000" / "01-2607-3-2359" / "01-2607-3-2359.pdf").write_bytes(b"%PDF")
    # 파일명 뒤에 이름 붙은 건(유일할 때만 인정)
    (cat / "0001~0500" / "01-2601-3-0084(서울금남새마을금고)").mkdir(parents=True)
    (cat / "0001~0500" / "01-2601-3-0084(서울금남새마을금고)" / "01-2601-3-0084 유청은.pdf").write_bytes(b"%PDF")
    (cat / "0001~0500" / "01-2601-3-0084(서울금남새마을금고)" / "공부서류.pdf").write_bytes(b"%PDF")
    return cat


def test_parse_and_range():
    assert archive.parse_doc("01-2608-3-2676") == ("01", 2026, "3", 2676)
    assert archive.range_folder(2676) == "2501~3000"
    assert archive.range_folder(1) == "0001~0500" and archive.range_folder(500) == "0001~0500"
    assert archive.range_folder(501) == "0501~1000" and archive.range_folder(1000) == "0501~1000"


def test_find_pdf_regular(tmp_path):
    _make(tmp_path)
    assert archive.find_pdf("01-2608-3-2676", root=tmp_path).name == "01-2608-3-2676.pdf"


def test_find_pdf_suffix_folder(tmp_path):
    _make(tmp_path)
    assert archive.find_pdf("01-2601-3-0008", root=tmp_path).parent.name == "01-2601-3-0008(HUG)"


def test_find_pdf_misplaced_range(tmp_path):
    _make(tmp_path)
    assert archive.find_pdf("01-2607-3-2359", root=tmp_path).parent.parent.name == "2501~3000"


def test_find_pdf_loose_name_only_if_unique(tmp_path):
    _make(tmp_path)
    assert archive.find_pdf("01-2601-3-0084", root=tmp_path).name == "01-2601-3-0084 유청은.pdf"


def test_find_pdf_missing(tmp_path):
    _make(tmp_path)
    with pytest.raises(archive.ArchiveError):
        archive.find_pdf("01-2608-3-2999", root=tmp_path)


def test_year_folder_prefers_zero_prefix(tmp_path):
    (tmp_path / "1-2020년 online전례").mkdir()
    (tmp_path / "0-2020년 online전례").mkdir()
    assert archive.year_folder(tmp_path, 2020).name == "0-2020년 online전례"


def test_find_survey_pdf(tmp_path):
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2703"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2703.pdf").write_bytes(b"x")
    import pytest
    with pytest.raises(archive.ArchiveError):
        archive.find_survey_pdf("01-2608-3-2703", root=tmp_path)      # 감정서 PDF 로 대신하지 않는다
    (folder / "01-2608-3-2703 현장조사.pdf").write_bytes(b"x")
    assert archive.find_survey_pdf("01-2608-3-2703", root=tmp_path).name == "01-2608-3-2703 현장조사.pdf"


def test_find_related_pdf(tmp_path):
    folder = tmp_path / "2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2703"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2703.pdf").write_bytes(b"%PDF")
    with pytest.raises(archive.ArchiveError):
        archive.find_related_pdf("01-2608-3-2703", "수수료", root=tmp_path)
    (folder / "01-2608-3-2703 수수료.pdf").write_bytes(b"%PDF")
    (folder / "01-2608-3-2703 공부.pdf").write_bytes(b"%PDF")
    assert archive.find_related_pdf("01-2608-3-2703", "수수료", root=tmp_path).name == "01-2608-3-2703 수수료.pdf"
    assert archive.find_related_pdf("01-2608-3-2703", "공부", root=tmp_path).name == "01-2608-3-2703 공부.pdf"


def test_find_survey_pdf_ibk_no_number(tmp_path):
    """기업 전례: 번호 없는 '현장조사서.pdf'(2704) — 번호형이 없을 때만, 1개일 때만."""
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2704"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2704.pdf").write_bytes(b"x" * 10)
    with pytest.raises(archive.ArchiveError):
        archive.find_survey_pdf("01-2608-3-2704", root=tmp_path)
    (folder / "현장조사서.pdf").write_bytes(b"x" * 10)
    assert archive.find_survey_pdf("01-2608-3-2704", root=tmp_path).name == "현장조사서.pdf"
    (folder / "01-2608-3-2704 현장조사.pdf").write_bytes(b"x" * 10)
    assert archive.find_survey_pdf("01-2608-3-2704", root=tmp_path).name == "01-2608-3-2704 현장조사.pdf"   # 번호형 우선


def test_find_pdf_skips_related_and_tolerates_typo(tmp_path):
    """2684 실물: 감정서 파일명이 '01-26208-3-2684.pdf'(오타)라 접두 매칭이 안 되고 현장조사 PDF 만 접두가 맞던 사고."""
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2684"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2684 현장조사.pdf").write_bytes(b"x" * 10)
    (folder / "의뢰서.pdf").write_bytes(b"x" * 10)
    with pytest.raises(archive.ArchiveError):
        archive.find_pdf("01-2608-3-2684", root=tmp_path)          # 현장조사 PDF 를 감정서로 집지 않는다
    (folder / "01-26208-3-2684.pdf").write_bytes(b"x" * 10)
    assert archive.find_pdf("01-2608-3-2684", root=tmp_path).name == "01-26208-3-2684.pdf"
    assert archive.find_survey_pdf("01-2608-3-2684", root=tmp_path).name == "01-2608-3-2684 현장조사.pdf"


def test_find_related_pdf_bare_names_2711(tmp_path):
    """2711 실물(2026-08-31): 번호 없는 '공부.pdf'·'청구서.pdf'·'현장조사서.pdf' 만 있음 → 청구서=수수료, 번호 없는 파일 허용."""
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2711"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2711.pdf").write_bytes(b"%PDF")
    (folder / "공부.pdf").write_bytes(b"%PDF")
    (folder / "청구서.pdf").write_bytes(b"%PDF")
    (folder / "현장조사서.pdf").write_bytes(b"%PDF")
    assert archive.find_related_pdf("01-2608-3-2711", "수수료", root=tmp_path).name == "청구서.pdf"
    assert archive.find_related_pdf("01-2608-3-2711", "공부", root=tmp_path).name == "공부.pdf"
    assert archive.find_survey_pdf("01-2608-3-2711", root=tmp_path).name == "현장조사서.pdf"
    assert archive.find_pdf("01-2608-3-2711", root=tmp_path).name == "01-2608-3-2711.pdf"   # 청구서 등은 감정서로 안 집음


def test_find_related_pdf_priority_and_ambiguity(tmp_path):
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2712"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2712.pdf").write_bytes(b"%PDF")
    (folder / "청구서.pdf").write_bytes(b"%PDF")
    (folder / "01-2608-3-2712 수수료.pdf").write_bytes(b"%PDF")
    assert archive.find_related_pdf("01-2608-3-2712", "수수료", root=tmp_path).name == "01-2608-3-2712 수수료.pdf"   # 번호형 우선
    (folder / "01-2608-3-2712 수수료.pdf").unlink()
    (folder / "수수료.pdf").write_bytes(b"%PDF")
    assert archive.find_related_pdf("01-2608-3-2712", "수수료", root=tmp_path).name == "수수료.pdf"   # 번호 없는 것끼리는 수수료 > 청구서
    (folder / "공부.pdf").write_bytes(b"%PDF")
    (folder / "공부2.pdf").write_bytes(b"%PDF")
    with pytest.raises(archive.ArchiveError, match="후보 2개"):
        archive.find_related_pdf("01-2608-3-2712", "공부", root=tmp_path)                   # 2개면 고르지 않음
    with pytest.raises(archive.ArchiveError):
        archive.find_related_pdf("01-2608-3-2712", "현장조사", root=tmp_path)               # 없으면 감정서로 대신 안 함


def test_locate_pdf_skips_missing_but_fails_on_broken(tmp_path):
    """러너용 locate_pdf: 자동 탐색에서 못 찾으면 (None, 사유)로 건너뜀(입력·저장은 진행, 완료 — 사용자 결정 2026-09-03).
    자동 탐색한 깨진 파일(1000B 미만)도 건너뜀(2026-09-07). --pdf 지정 파일 없음·깨짐만 ArchiveError(fail-closed, 수동 실행용)."""
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2608-3-2720"
    folder.mkdir(parents=True)
    (folder / "01-2608-3-2720.pdf").write_bytes(b"%PDF" * 300)
    path, why = archive.locate_pdf("01-2608-3-2720", "감정서", root=tmp_path)
    assert path.name == "01-2608-3-2720.pdf" and why is None
    for kind in ("현장조사", "수수료", "공부"):                          # 폴더는 있고 그 PDF 만 없음 → 건너뜀
        path, why = archive.locate_pdf("01-2608-3-2720", kind, root=tmp_path)
        assert path is None and "못 찾았습니다" in why
    path, why = archive.locate_pdf("01-2608-3-2999", "감정서", root=tmp_path)   # 감정서 폴더 자체가 없음 → 건너뜀
    assert path is None and why
    path, why = archive.locate_pdf("01-2608-3-2999", "현장조사", root=tmp_path)  # 감정서 없으면 현장조사도 건너뜀
    assert path is None and why
    (folder / "01-2608-3-2720 현장조사.pdf").write_bytes(b"x")                  # 있는데 깨진 파일 → 그 PDF 만 건너뜀(2026-09-07)
    path, why = archive.locate_pdf("01-2608-3-2720", "현장조사", root=tmp_path)
    assert path is None and "깨진 파일" in why
    with pytest.raises(archive.ArchiveError):                                      # 지정 파일이 없음 → 중단
        archive.locate_pdf("01-2608-3-2720", "감정서", str(folder / "없음.pdf"), root=tmp_path)
    explicit = folder / "지정.pdf"
    explicit.write_bytes(b"%PDF" * 300)
    assert archive.locate_pdf("01-2608-3-2720", "감정서", str(explicit), root=tmp_path) == (explicit, None)


def test_related_pdf_found_without_appraisal_pdf(tmp_path):
    """관련 서류는 감정서 PDF 보다 먼저 올라오는 일이 흔하다(2776 실측 2026-09-07) — 폴더만 있으면 현장조사서를 찾는다."""
    folder = tmp_path / "0-2026년 on-line전례" / "3-담보" / "2501~3000" / "01-2609-3-2776"
    folder.mkdir(parents=True)
    (folder / "현장조사서.pdf").write_bytes(b"%PDF" * 300)
    (folder / "의뢰서.pdf").write_bytes(b"%PDF" * 300)
    path, why = archive.locate_pdf("01-2609-3-2776", "감정서", root=tmp_path)
    assert path is None and why                                                  # 감정서는 아직 없음 → 건너뜀
    path, why = archive.locate_pdf("01-2609-3-2776", "현장조사", root=tmp_path)
    assert path is not None and path.name == "현장조사서.pdf" and why is None     # 현장조사서는 붙는다
    path, why = archive.locate_pdf("01-2609-3-2999", "현장조사", root=tmp_path)
    assert path is None and why                                                  # 폴더 자체가 없으면 여전히 건너뜀

