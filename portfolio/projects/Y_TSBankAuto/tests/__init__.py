# -*- coding: utf-8 -*-
"""테스트 패키지. import 시 프로젝트 루트를 sys.path 에 추가하고 격리 가드 설치."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests import _fakes  # noqa: E402

_fakes.install_isolation_guards()
