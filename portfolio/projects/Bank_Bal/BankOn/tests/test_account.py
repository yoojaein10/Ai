"""수수료 청구서 계좌 파싱 — 실제 `APW_Bill.Account` 값으로 검증."""
from __future__ import annotations

from bankon.parse.account import parse_accounts, primary_account


def test_표준형식을_파싱한다():
    text = "\r\n◈ 신한은행                : 100-025-471640      ( 예금주 :(주)대화감정평가법인 )"
    account = primary_account(text)
    assert account is not None
    assert account.bank == "신한은행"
    assert account.number == "100-025-471640"
    assert account.holder == "(주)대화감정평가법인"


def test_괄호앞_공백이_없어도_파싱한다():
    text = "\r\n◈ 국민은행 남부터미널역       : 484201-01-128982(예금주:(주)대화감정평가법인 본사 )"
    account = primary_account(text)
    assert account is not None
    assert account.bank == "국민은행 남부터미널역"
    assert account.number == "484201-01-128982"
    assert account.holder == "(주)대화감정평가법인 본사"


def test_은행명이_없어도_계좌를_뽑는다():
    text = "    : 022-6000-1855-706   ( 예금주 :(주)대화감정평가법인 )"
    account = primary_account(text)
    assert account is not None
    assert account.number == "022-6000-1855-706"
    assert account.bank == ""


def test_계좌가_여러개면_모두_뽑고_첫번째를_쓴다():
    text = (
        "◈ 신한은행 : 100-025-471640 ( 예금주 :(주)대화감정평가법인 )\r\n"
        "◈ 국민은행 : 618701-04-281236 ( 예금주 :(주)대화감정평가법인 경북지사 )"
    )
    accounts = parse_accounts(text)
    assert len(accounts) == 2
    assert primary_account(text).number == "100-025-471640"
    assert accounts[1].holder == "(주)대화감정평가법인 경북지사"


def test_계좌가_아닌_문구는_빈결과():
    # 실제 값: 카드결제 안내만 있고 계좌번호가 없다.
    text = '\r\n◈ 부산은행       : 카드결제시연락주세요( 담당자 : 샘플사용자(051-632-3300)   )'
    assert parse_accounts(text) == ()
    assert primary_account(text) is None


def test_빈값이면_None():
    assert primary_account(None) is None
    assert primary_account("") is None
    assert primary_account("\r\n\r\n") is None
