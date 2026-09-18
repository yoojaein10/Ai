from pathlib import Path
from bankon.ui import form


def test_load_combo_lists_order():
    lists = form.load_combo_lists(Path(__file__).resolve().parent.parent / "recon" / "combo_shinhan.md")
    assert lists["담보용도"].index("공장용지") == 13 and lists["담보용도"].index("공장") == 40
    assert lists["용도지역구분(신)"].index("농림지역미분류") + 1 == lists["용도지역구분(신)"].index("농림지역")
    assert form._index_in(lists["담보종류"], "공장") == 79
