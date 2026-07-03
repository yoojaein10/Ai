"""10단계 테스트: 마인드맵 구조 검증(루트·고아·순환), Mermaid 렌더링."""

import pytest

from src.generate import Mindmap, MindmapNode, render_mermaid, validate_mindmap


def _map(nodes):
    return Mindmap(nodes=[MindmapNode(**n) for n in nodes])


def _valid():
    return _map([
        {"id": "n1", "label": "쇼츠 전략", "parent_id": ""},
        {"id": "n2", "label": "수익화 방식", "parent_id": "n1"},
        {"id": "n3", "label": "수입형", "parent_id": "n2"},
        {"id": "n4", "label": "확장형", "parent_id": "n2"},
        {"id": "n5", "label": "AI 활용", "parent_id": "n1"},
    ])


# --- 구조 검증 ----------------------------------------------------------------

def test_validate_ok():
    assert validate_mindmap(_valid()) == []


def test_validate_no_root():
    m = _map([{"id": "n1", "label": "a", "parent_id": "n2"}, {"id": "n2", "label": "b", "parent_id": "n1"}])
    problems = validate_mindmap(m)
    assert any("루트" in p for p in problems)


def test_validate_multiple_roots():
    m = _map([{"id": "n1", "label": "a", "parent_id": ""}, {"id": "n2", "label": "b", "parent_id": ""}])
    assert any("루트 노드가 2개" in p for p in validate_mindmap(m))


def test_validate_orphan_parent():
    m = _map([{"id": "n1", "label": "a", "parent_id": ""}, {"id": "n2", "label": "b", "parent_id": "없는id"}])
    assert any("존재하지 않는 부모" in p for p in validate_mindmap(m))


def test_validate_cycle():
    m = _map([
        {"id": "n1", "label": "루트", "parent_id": ""},
        {"id": "n2", "label": "a", "parent_id": "n3"},
        {"id": "n3", "label": "b", "parent_id": "n2"},  # n2 ↔ n3 순환
    ])
    assert any("순환" in p for p in validate_mindmap(m))


def test_validate_duplicate_ids():
    m = _map([{"id": "n1", "label": "a", "parent_id": ""}, {"id": "n1", "label": "b", "parent_id": "n1"}])
    assert any("중복" in p for p in validate_mindmap(m))


# --- Mermaid 렌더링 ------------------------------------------------------------

def test_render_hierarchy_indentation():
    out = render_mermaid(_valid())
    lines = out.split("\n")
    assert lines[0] == "mindmap"
    assert "root((쇼츠 전략))" in lines[1]
    # 계층 = 들여쓰기: 수익화 방식(2단) < 수입형(3단)
    idx_way = next(i for i, l in enumerate(lines) if l.strip() == "수익화 방식")
    idx_imp = next(i for i, l in enumerate(lines) if l.strip() == "수입형")
    indent = lambda s: len(s) - len(s.lstrip())
    assert indent(lines[idx_imp]) > indent(lines[idx_way])


def test_render_sanitizes_parentheses():
    m = _map([
        {"id": "n1", "label": "루트", "parent_id": ""},
        {"id": "n2", "label": "확장형(Expansion)", "parent_id": "n1"},
    ])
    out = render_mermaid(m)
    assert "(" not in out.split("\n", 2)[2]      # 자식 노드 줄에 반각 괄호가 없어야 함
    assert "확장형（Expansion）" in out          # 전각(U+FF08/09)으로 치환


def test_render_no_root_raises():
    m = Mindmap(nodes=[MindmapNode(id="n1", label="a", parent_id="ghost")])
    with pytest.raises(ValueError):
        render_mermaid(m)
