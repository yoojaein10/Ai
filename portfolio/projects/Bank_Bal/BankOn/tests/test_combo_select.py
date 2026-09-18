from bankon.ui import form


def test_combo_norm_and_keys():
    assert form._combo_norm("김치암(4189)") == form._combo_norm("김치암")
    assert form._combo_norm("농림지역미분류") != form._combo_norm("농림지역")
    assert form._keys("상가(중/소형)") == "상가{(}중/소형{)}"
    assert form._keys("농림지역") == "농림지역"
