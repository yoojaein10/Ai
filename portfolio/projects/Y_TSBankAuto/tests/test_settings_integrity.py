# -*- coding: utf-8 -*-
"""settings 무결성 게이트 테스트 (지시 §8, §16)."""
import os
import tempfile
import unittest

import settings_integrity as si


class TestEvaluate(unittest.TestCase):
    def _safe_facts(self, **over):
        f = si.IntegrityFacts(
            path="x", exists=True, verifiable=True, is_reparse=False,
            parent_reparse=False, is_local=True, owner_ok=True,
            world_writable=False)
        for k, v in over.items():
            setattr(f, k, v)
        return f

    def test_safe_allows_real(self):
        r = si.evaluate(self._safe_facts())
        self.assertTrue(r.real_allowed)
        self.assertEqual(r.reasons, [])

    def test_missing_blocks_real_but_fake_ok(self):
        r = si.evaluate(si.IntegrityFacts(path="x", exists=False))
        self.assertFalse(r.real_allowed)
        self.assertTrue(r.fake_allowed)

    def test_world_writable_blocks(self):
        r = si.evaluate(self._safe_facts(world_writable=True))
        self.assertFalse(r.real_allowed)
        self.assertTrue(any("쓰기 권한" in x for x in r.reasons))

    def test_reparse_blocks(self):
        self.assertFalse(si.evaluate(self._safe_facts(is_reparse=True)).real_allowed)
        self.assertFalse(si.evaluate(self._safe_facts(parent_reparse=True)).real_allowed)

    def test_network_path_blocks(self):
        self.assertFalse(si.evaluate(self._safe_facts(is_local=False)).real_allowed)

    def test_unverifiable_blocks(self):
        self.assertFalse(si.evaluate(self._safe_facts(verifiable=False)).real_allowed)

    def test_untrusted_owner_blocks(self):
        self.assertFalse(si.evaluate(self._safe_facts(owner_ok=False)).real_allowed)


class TestGather(unittest.TestCase):
    def test_gather_on_real_file(self):
        # 사용자가 만든 임시 파일: 소유자/ACL 확인이 되면 안전으로 평가되어야 한다.
        fd, path = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        try:
            facts = si.gather_facts(path)
            self.assertTrue(facts.exists)
            self.assertFalse(facts.is_reparse)
            # verifiable 이면 소유자는 현재 사용자여야 한다.
            if facts.verifiable:
                self.assertTrue(facts.owner_ok)
        finally:
            os.remove(path)

    def test_missing_file_facts(self):
        facts = si.gather_facts(os.path.join(tempfile.gettempdir(), "no_such_x.ini"))
        self.assertFalse(facts.exists)

    def test_unc_not_local(self):
        facts = si.gather_facts(r"\\server\share\settings.ini")
        self.assertFalse(facts.is_local)


class TestAceComponents(unittest.TestCase):
    """일반/object ACE 분해가 안전한지(SID 는 항상 마지막)."""

    def test_normal_ace_3tuple(self):
        ace = ((0, 0), 0x120089, "SID-USER")   # ((type,flags), mask, sid)
        self.assertEqual(si._ace_components(ace), (0, 0, 0x120089, "SID-USER"))

    def test_object_ace_longer(self):
        # object ACE: ((type,flags), mask, objflags, objtype, inhtype, sid)
        ace = ((5, 0x08), 0x2, 1, "GUID1", "GUID2", "SID-BROAD")
        self.assertEqual(si._ace_components(ace), (5, 0x08, 0x2, "SID-BROAD"))

    def test_bad_header_raises(self):
        with self.assertRaises(si._AclError):
            si._ace_components((0, 0x1, "SID"))   # header 가 튜플이 아님


class TestClassifyWorldWritable(unittest.TestCase):
    WB = 0b1000     # 테스트용 쓰기 비트
    RD = 0b0001     # 테스트용 읽기 비트
    ALLOW, DENY, ALLOW_OBJ, AUDIT, UNKNOWN = 0, 1, 5, 2, 99

    def _is_broad(self, k):
        return k == "BROAD"

    def _run(self, aces):
        return si._classify_world_writable(aces, self._is_broad, self.WB)

    def test_allow_broad_write_is_writable(self):
        self.assertTrue(self._run([(self.ALLOW, 0, self.WB, "BROAD")]))

    def test_allow_broad_readonly_not_writable(self):
        self.assertFalse(self._run([(self.ALLOW, 0, self.RD, "BROAD")]))

    def test_allow_nonbroad_write_not_writable(self):
        self.assertFalse(self._run([(self.ALLOW, 0, self.WB, "USER")]))

    def test_deny_before_allow_blocks(self):
        # 정규 DACL: DENY(쓰기) 가 앞서면 이후 ALLOW 쓰기는 무효
        self.assertFalse(self._run([
            (self.DENY, 0, self.WB, "BROAD"),
            (self.ALLOW, 0, self.WB, "BROAD"),
        ]))

    def test_allow_then_deny_order_sensitive(self):
        # 비정규 순서: ALLOW 가 먼저면 광역 쓰기로 판정(fail-closed 방향)
        self.assertTrue(self._run([
            (self.ALLOW, 0, self.WB, "BROAD"),
            (self.DENY, 0, self.WB, "BROAD"),
        ]))

    def test_inherit_only_skipped(self):
        self.assertFalse(self._run([(self.ALLOW, si._INHERIT_ONLY_ACE, self.WB, "BROAD")]))

    def test_audit_ace_skipped(self):
        self.assertFalse(self._run([(self.AUDIT, 0, self.WB, "BROAD")]))

    def test_object_allow_write_is_writable(self):
        self.assertTrue(self._run([(self.ALLOW_OBJ, 0, self.WB, "BROAD")]))

    def test_unknown_ace_fails_closed(self):
        with self.assertRaises(si._AclError):
            self._run([(self.UNKNOWN, 0, self.WB, "BROAD")])

    def test_null_dacl_via_wrapper(self):
        class _SD:
            def GetSecurityDescriptorDacl(self):
                return None
        self.assertTrue(si._dacl_world_writable(_SD()))   # NULL DACL → 위험

    def test_unknown_ace_blocks_real_via_gather(self):
        # _AclError → gather_facts 가 verifiable=False → evaluate 가 real 차단
        facts = si.IntegrityFacts(path="x", exists=True, verifiable=False,
                                  is_local=True, owner_ok=True)
        self.assertFalse(si.evaluate(facts).real_allowed)


class TestResolvePath(unittest.TestCase):
    def test_resolves_to_settings_ini(self):
        self.assertTrue(si.resolve_settings_path().endswith("settings.ini"))
        # _internal / _MEIPASS 를 사용하지 않는다.
        self.assertNotIn("_internal", si.resolve_settings_path())
        self.assertNotIn("_MEI", si.resolve_settings_path())


if __name__ == "__main__":
    unittest.main()
