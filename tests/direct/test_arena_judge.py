# -*- coding: utf-8 -*-
"""ArenaJudge direct-mode tests — escrowed prize pools settled by an on-chain referee.

Run: pytest tests/direct/ -v
"""

PRIZE = 1000000000000000     # 0.001 GEN
W3 = "0x07F0ED876895ebb9C9944b31A8Be7Dcded31AaC1"   # third wallet used as player B
MAX_ROUNDS = 3


def _deploy(direct_vm, direct_deploy, host=None):
    import pathlib
    import tempfile

    src = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "arena_judge.py"
    code = src.read_text(encoding="utf-8")
    tmp = pathlib.Path(tempfile.gettempdir()) / "arena_judge_local.py"
    tmp.write_text(code, encoding="utf-8")
    if host is not None:
        direct_vm.sender = host
    return direct_deploy(str(tmp))


def _addr(v):
    from genlayer import Address
    return Address(v)


def _match(direct_vm, c, host, a, b, prize=PRIZE,
           title="Finals", rules="Best of three, highest score wins"):
    direct_vm.sender = host
    direct_vm.value = prize
    mid = c.create_match(title, rules, _addr(a), _addr(b))
    direct_vm.value = 0
    return mid


def _evidence(direct_vm, c, who, mid, url):
    direct_vm.sender = who
    c.submit_evidence(mid, url)


def _verdict(winner="A", score=85, conf="high"):
    return {"inconclusive": False, "winner": winner, "score": score,
            "confidence": conf, "reason": "Artefacts adjudicated."}


# ================================================= 1. creation

def test_create_requires_prize(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = 0
    with direct_vm.expect_revert("A prize is required"):
        c.create_match("Finals", "Best of three", _addr(direct_bob), _addr(direct_alice))


def test_create_validation(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = PRIZE
    with direct_vm.expect_revert("Title is required"):
        c.create_match("", "Best of three", _addr(direct_bob), _addr(direct_alice))
    with direct_vm.expect_revert("Title is too long"):
        c.create_match("x" * 97, "Best of three", _addr(direct_bob), _addr(direct_alice))
    with direct_vm.expect_revert("Rules are required"):
        c.create_match("Finals", "", _addr(direct_bob), _addr(direct_alice))
    with direct_vm.expect_revert("Rules are too long"):
        c.create_match("Finals", "y" * 701, _addr(direct_bob), _addr(direct_alice))
    direct_vm.value = 0


def test_host_cannot_also_play(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = PRIZE
    with direct_vm.expect_revert("The host cannot also play"):
        c.create_match("Finals", "Best of three", _addr(direct_alice), _addr(direct_bob))
    direct_vm.value = 0


def test_players_must_differ(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = PRIZE
    with direct_vm.expect_revert("The two players must differ"):
        c.create_match("Finals", "Best of three", _addr(direct_bob), _addr(direct_bob))
    direct_vm.value = 0


def test_prize_is_custody(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=2500)
    m = c.get_match(mid)
    assert int(m["prize"]) == 2500
    assert int(m["state"]) == 0
    assert m["settled"] is False
    assert int(m["rounds"]) == 0
    assert m["host"].lower() == "0x" + bytes(direct_alice).hex()


# ================================================= 2. evidence

def test_only_named_players_submit(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    direct_vm.sender = direct_alice          # host
    with direct_vm.expect_revert("Only the two named players can submit evidence"):
        c.submit_evidence(mid, "https://example.com/a")


def test_evidence_url_validation(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("A valid evidence URL is required"):
        c.submit_evidence(mid, "not-a-url")
    with direct_vm.expect_revert("Evidence URL is too long"):
        c.submit_evidence(mid, "https://e.com/" + "z" * 510)


def test_both_sides_recorded(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/bob-log")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/alice-log")
    m = c.get_match(mid)
    assert m["evidence_a"] == "https://example.com/bob-log"     # player A = direct_bob
    assert m["evidence_b"] == "https://example.com/alice-log"   # player B = W3


# ================================================= 3. judging

def test_judge_requires_both_evidence(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Both players must submit evidence first"):
        c.judge_match(mid)


def test_verdict_is_one_shot(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*example\.com.*", {"status": 200, "body": "<html>score 21-18 with timestamps</html>"})
    direct_vm.mock_llm(r".*", _verdict("A", 88))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    with direct_vm.expect_revert("Match already has a verdict"):
        c.judge_match(mid)


def test_unreachable_evidence_is_inconclusive(direct_vm, direct_deploy, direct_alice, direct_bob):
    """A network failure must never hand the prize to anyone."""
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 503, "body": ""})
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    m = c.get_match(mid)
    assert int(m["state"]) == 2          # INCONCLUSIVE
    assert int(m["rounds"]) == 1
    assert m["settled"] is False
    with direct_vm.expect_revert("Match has no final verdict"):
        c.claim_prize(mid)


def test_rounds_are_bounded(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 503, "body": ""})
    direct_vm.sender = direct_alice
    for _ in range(MAX_ROUNDS):
        c.judge_match(mid)
    assert int(c.get_match(mid)["rounds"]) == MAX_ROUNDS
    with direct_vm.expect_revert("Judging rounds exhausted"):
        c.judge_match(mid)


def test_malformed_verdict_is_inconclusive(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>x</html>"})
    direct_vm.mock_llm(r".*", {"winner": "A"})     # missing keys
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    assert int(c.get_match(mid)["state"]) == 2


# ================================================= 4. verdicts and payouts

def test_a_wins_takes_prize(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=1000)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>a won clearly</html>"})
    direct_vm.mock_llm(r".*", _verdict("A", 90))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    assert int(c.get_match(mid)["winner"]) == 1
    c.claim_prize(mid)
    assert int(c.get_credit(_addr(direct_bob))) == 1000     # player A = direct_bob


def test_b_wins_takes_prize(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=1000)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>b won clearly</html>"})
    direct_vm.mock_llm(r".*", _verdict("B", 92))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    assert int(c.get_match(mid)["winner"]) == 2
    c.claim_prize(mid)
    assert int(c.get_credit(_addr(W3))) == 1000             # player B = W3


def test_draw_splits_prize(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=1001)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>equivalent</html>"})
    direct_vm.mock_llm(r".*", _verdict("draw", 60))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    assert int(c.get_match(mid)["winner"]) == 3
    c.claim_prize(mid)
    a_credit = int(c.get_credit(_addr(direct_bob)))
    b_credit = int(c.get_credit(_addr(W3)))
    assert a_credit + b_credit == 1001
    assert abs(a_credit - b_credit) <= 1        # odd prize splits fairly


def test_claim_twice_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>x</html>"})
    direct_vm.mock_llm(r".*", _verdict("A", 80))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    _m = c.get_match(mid)
    print("\n>>> DBG after judge: state=", _m["state"], "winner=", _m["winner"], "rounds=", _m["rounds"], "reason=", _m["reason"][:80])
    c.claim_prize(mid)
    with direct_vm.expect_revert("Prize already settled"):
        c.claim_prize(mid)


def test_claim_requires_verdict(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Match has no final verdict"):
        c.claim_prize(mid)


# ================================================= 5. refund and pull

def test_host_refund_after_rounds_exhausted(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=1000)

    # an OPEN match is refundable (nobody played) — this is the host's safety valve;
    # the "rounds remain" guard only applies once judging has begun and stayed inconclusive

    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 503, "body": ""})
    for _ in range(MAX_ROUNDS):
        c.judge_match(mid)

    direct_vm.sender = direct_bob               # only host refunds
    with direct_vm.expect_revert("Only the host can refund"):
        c.refund(mid)

    direct_vm.sender = direct_alice
    c.refund(mid)
    assert int(c.get_match(mid)["state"]) == 4
    assert int(c.get_credit(_addr(direct_alice))) == 1000


def test_refund_blocked_when_verdict_exists(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>x</html>"})
    direct_vm.mock_llm(r".*", _verdict("A", 85))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    with direct_vm.expect_revert("A verdict exists; claim it instead"):
        c.refund(mid)


def test_withdraw_credit_clears_before_transfer(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=1000)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>x</html>"})
    direct_vm.mock_llm(r".*", _verdict("B", 90))
    direct_vm.sender = direct_alice
    c.judge_match(mid)
    c.claim_prize(mid)

    assert int(c.get_credit(_addr(W3))) == 1000
    direct_vm.sender = _addr(W3)
    c.withdraw_credit()
    assert int(c.get_credit(_addr(W3))) == 0
    with direct_vm.expect_revert("No credit to withdraw"):
        c.withdraw_credit()


# ================================================= 6. pagination

def test_pagination_is_bounded(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    for i in range(5):
        _match(direct_vm, c, direct_alice, direct_bob, W3, title="M" + str(i))
    p1 = c.get_page(0, 2)
    assert int(p1["total"]) == 5
    assert len(p1["items"]) == 2
    assert int(p1["items"][0]["id"]) == 1
    big = c.get_page(0, 999)
    assert len(big["items"]) == 5


# ================================================= 7. lifecycle

def test_full_match_lifecycle(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    mid = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=1000)
    _evidence(direct_vm, c, direct_bob, mid, "https://example.com/b")
    _evidence(direct_vm, c, _addr(W3), mid, "https://example.com/a")
    direct_vm.mock_web(r".*", {"status": 200, "body": "<html>b defeated a</html>"})
    direct_vm.mock_llm(r".*", _verdict("B", 93))
    direct_vm.sender = direct_alice
    c.judge_match(mid)

    m = c.get_match(mid)
    assert int(m["state"]) == 1          # JUDGED
    assert m["reason"] != ""
    assert m["confidence"] == "high"

    c.claim_prize(mid)
    assert int(c.get_match(mid)["state"]) == 3     # PAID
    assert int(c.get_credit(_addr(W3))) == 1000
    direct_vm.sender = _addr(W3)
    c.withdraw_credit()
    assert int(c.get_credit(_addr(W3))) == 0


def test_prize_always_reaches_a_terminal_state(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Won, refunded — the prize never stays stranded."""
    c = _deploy(direct_vm, direct_deploy, direct_alice)

    won = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=500, title="Won")
    _evidence(direct_vm, c, direct_bob, won, "https://example.com/won-b")
    _evidence(direct_vm, c, _addr(W3), won, "https://example.com/won-a")
    direct_vm.mock_web(r".*example\.com/won.*", {"status": 200, "body": "<html>clear result</html>"})
    direct_vm.mock_llm(r".*clear result.*", _verdict("A", 88))
    direct_vm.sender = direct_alice
    c.judge_match(won)
    c.claim_prize(won)

    stuck = _match(direct_vm, c, direct_alice, direct_bob, W3, prize=500, title="Stuck")
    _evidence(direct_vm, c, direct_bob, stuck, "https://example.com/stuck-b")
    _evidence(direct_vm, c, _addr(W3), stuck, "https://example.com/stuck-a")
    direct_vm.mock_web(r".*", {"status": 503, "body": ""})
    for _ in range(MAX_ROUNDS):
        c.judge_match(stuck)
    direct_vm.sender = direct_alice          # host refunds
    c.refund(stuck)

    assert int(c.get_match(won)["state"]) == 3
    assert int(c.get_match(stuck)["state"]) == 4
    # player_a got 500 (won), host got 500 back (refund)
    assert int(c.get_credit(_addr(direct_bob))) == 500
    assert int(c.get_credit(_addr(direct_alice))) == 500
