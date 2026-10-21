import pytest

CONTRACT = "contracts/arena_judge.py"

RULES = "Best of three; the side with the higher verified final score wins."
URL_A = "https://example.com/a-packet.md"
URL_B = "https://example.com/b-packet.md"

PACKET_A = ("Packet A: round one 11-9, round two 11-7, round three 11-13. Totals 33-29. "
            "Screenshot timestamps and referee signature attached for every round.")
PACKET_B = ("Packet B: round one 9-11, round two 7-11, round three 13-11. Totals 29-33. "
            "Same three rounds, no referee signature attached.")

GOOD_A = {"inconclusive": False, "winner": 0, "score": 88, "confidence": "high",
          "decided": True, "reason": "A wins two of three rounds with signed scorecards."}
GOOD_B = {"inconclusive": False, "winner": 1, "score": 80, "confidence": "high",
          "decided": True, "reason": "B outscored A in the decisive round."}
DRAW = {"inconclusive": False, "winner": 2, "score": 50, "confidence": "medium",
        "decided": True, "reason": "The packets do not separate the sides."}
UNDECIDABLE = {"inconclusive": False, "winner": 2, "score": 10, "confidence": "low",
               "decided": False, "reason": "Evidence conflicts and cannot be reconciled."}


@pytest.fixture
def arena(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    direct_vm.sender = direct_alice          # host
    c = direct_deploy(CONTRACT)
    direct_vm.value = 2 * 10**17             # 0.2 GEN prize
    c.create_match("Grand Final", RULES, direct_bob, direct_charlie, 3600)
    direct_vm.value = 0
    return c


def commit(direct_vm, c, who, url, mid=0):
    direct_vm.sender = who
    c.submit_evidence(mid, url)
    return mid


# ---------------- custody and creation ----------------

def test_create_match_escrows_the_prize(direct_vm, arena, direct_alice, direct_bob, direct_charlie):
    m = arena.get_match(0)
    assert m["prize"] == 2 * 10**17
    assert m["state"] == 0                       # S_OPEN
    assert m["submitted_a"] is False
    assert m["submitted_b"] is False
    assert m["evidence_count"] == 0
    host = m["host"].lower().replace("0x", "")
    assert host == direct_alice.hex().lower().replace("0x", "")


def test_prize_is_required(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT)
    direct_vm.value = 0
    with pytest.raises(Exception):
        c.create_match("No prize", RULES, direct_bob, direct_charlie, 3600)


def test_host_cannot_also_play(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT)
    direct_vm.value = 10**17
    with pytest.raises(Exception):
        c.create_match("Self match", RULES, direct_alice, direct_bob, 3600)


def test_players_must_differ(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT)
    direct_vm.value = 10**17
    with pytest.raises(Exception):
        c.create_match("Same player", RULES, direct_bob, direct_bob, 3600)


def test_evidence_window_needs_a_minimum(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT)
    direct_vm.value = 10**17
    with pytest.raises(Exception):
        c.create_match("Too short", RULES, direct_bob, direct_charlie, 5)


# ---------------- evidence commitment ----------------

def test_evidence_is_committed_with_a_digest(direct_vm, arena, direct_bob):
    commit(direct_vm, arena, direct_bob, URL_A)
    m = arena.get_match(0)
    assert m["submitted_a"] is True
    assert m["url_a"] == URL_A
    assert m["digest_a"] != ""
    assert m["evidence_count"] == 1
    assert m["state"] == 0                      # still OPEN, only one side committed


def test_evidence_cannot_be_replaced(direct_vm, arena, direct_bob):
    commit(direct_vm, arena, direct_bob, URL_A)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        arena.submit_evidence(0, "https://example.com/rewritten.md")
    assert arena.get_match(0)["url_a"] == URL_A


def test_only_named_players_may_commit(direct_vm, arena, direct_alice):
    direct_vm.sender = direct_alice            # the host is not a player
    with pytest.raises(Exception):
        arena.submit_evidence(0, URL_A)


def test_both_sides_move_the_match_to_ready(direct_vm, arena, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    m = arena.get_match(0)
    assert m["evidence_count"] == 2
    assert m["state"] == 1                      # S_READY


def test_evidence_url_must_be_http(direct_vm, arena, direct_bob):
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        arena.submit_evidence(0, "ftp://example.com/a")
    with pytest.raises(Exception):
        arena.submit_evidence(0, "")


# ---------------- the refund hole the reviewer found ----------------

def test_refund_is_refused_after_one_side_commits(
        direct_vm, arena, direct_alice, direct_bob):
    """Previously the host could take the prize back while a player had already committed."""
    commit(direct_vm, arena, direct_bob, URL_A)
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        arena.refund(0)
    assert arena.get_match(0)["settled"] is False


def test_refund_is_refused_after_both_sides_commit(
        direct_vm, arena, direct_alice, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        arena.refund(0)
    assert arena.get_match(0)["state"] == 1


def test_refund_is_refused_while_the_window_is_open(
        direct_vm, arena, direct_alice):
    """Nobody committed, but players still have time - the host must wait."""
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        arena.refund(0)
    assert arena.get_match(0)["refundable"] is False


def test_refund_works_after_the_window_closes_with_no_evidence(
        direct_vm, arena, direct_alice):
    direct_vm.warp("2026-10-21T12:58:24.000Z")
    m = arena.get_match(0)
    assert m["refundable"] is True
    direct_vm.sender = direct_alice
    arena.refund(0)
    m = arena.get_match(0)
    assert m["settled"] is True
    assert m["state"] == 5                      # S_REFUNDED
    assert arena.get_credit(direct_alice) == 2 * 10**17


def test_only_the_host_can_refund(direct_vm, arena, direct_bob):
    direct_vm.warp("2026-10-21T12:58:24.000Z")
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        arena.refund(0)


def test_refund_is_refused_once_a_verdict_exists(
        direct_vm, arena, direct_alice, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 200, "body": PACKET_A})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": PACKET_B})
    direct_vm.mock_llm(r".*judge of an on-chain contest.*", GOOD_A)
    arena.judge_match(0)
    assert arena.get_match(0)["state"] == 2     # S_JUDGED
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        arena.refund(0)


# ---------------- judging ----------------

def test_judge_requires_both_evidence_packets(direct_vm, arena, direct_bob):
    commit(direct_vm, arena, direct_bob, URL_A)
    with pytest.raises(Exception):
        arena.judge_match(0)


def test_unreachable_artifact_makes_the_match_inconclusive(
        direct_vm, arena, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 404, "body": ""})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": PACKET_B})
    arena.judge_match(0)
    m = arena.get_match(0)
    assert m["state"] == 3                      # S_INCONCLUSIVE
    assert m["winner"] == 2
    assert "unusable" in m["reason"].lower() or "HTTP" in m["reason"]


def test_non_200_response_is_not_treated_as_evidence(
        direct_vm, arena, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 200, "body": PACKET_A})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 500, "body": PACKET_B})
    arena.judge_match(0)
    assert arena.get_match(0)["state"] == 3


def test_a_too_short_packet_cannot_decide_a_match(
        direct_vm, arena, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 200, "body": PACKET_A})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": "404 page not found"})
    arena.judge_match(0)
    assert arena.get_match(0)["state"] == 3


def test_decided_verdict_is_recorded(direct_vm, arena, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 200, "body": PACKET_A})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": PACKET_B})
    direct_vm.mock_llm(r".*judge of an on-chain contest.*", GOOD_A)
    arena.judge_match(0)
    m = arena.get_match(0)
    assert m["state"] == 2
    assert m["winner"] == 0
    assert m["score"] == 88
    assert m["digest_a"] != "" and m["digest_b"] != ""


def test_undecidable_verdict_becomes_inconclusive_not_a_win(
        direct_vm, arena, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 200, "body": PACKET_A})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": PACKET_B})
    direct_vm.mock_llm(r".*judge of an on-chain contest.*", UNDECIDABLE)
    arena.judge_match(0)
    m = arena.get_match(0)
    assert m["state"] == 3
    assert m["winner"] == 2


def test_rounds_are_bounded_then_refund_opens(
        direct_vm, arena, direct_alice, direct_bob, direct_charlie):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 404, "body": ""})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": PACKET_B})
    for _ in range(3):
        arena.judge_match(0)
    assert arena.get_match(0)["rounds"] == 3
    with pytest.raises(Exception):
        arena.judge_match(0)
    # evidence was committed, so refund is only reachable now that rounds are exhausted
    direct_vm.sender = direct_alice
    arena.refund(0)
    assert arena.get_match(0)["state"] == 5


# ---------------- payout ----------------

def _judge_for(direct_vm, arena, direct_bob, direct_charlie, verdict):
    commit(direct_vm, arena, direct_bob, URL_A)
    commit(direct_vm, arena, direct_charlie, URL_B)
    direct_vm.mock_web(r".*a-packet\.md", {"status": 200, "body": PACKET_A})
    direct_vm.mock_web(r".*b-packet\.md", {"status": 200, "body": PACKET_B})
    direct_vm.mock_llm(r".*judge of an on-chain contest.*", verdict)
    arena.judge_match(0)


def test_winner_is_credited_the_prize(direct_vm, arena, direct_bob, direct_charlie):
    _judge_for(direct_vm, arena, direct_bob, direct_charlie, GOOD_A)
    arena.claim_prize(0)
    assert arena.get_credit(direct_bob) == 2 * 10**17
    assert arena.get_credit(direct_charlie) == 0
    assert arena.get_match(0)["paid"] is True


def test_draw_splits_the_prize(direct_vm, arena, direct_bob, direct_charlie):
    _judge_for(direct_vm, arena, direct_bob, direct_charlie, DRAW)
    arena.claim_prize(0)
    assert arena.get_credit(direct_bob) == 10**17
    assert arena.get_credit(direct_charlie) == 10**17


def test_claim_is_idempotent(direct_vm, arena, direct_bob, direct_charlie):
    _judge_for(direct_vm, arena, direct_bob, direct_charlie, GOOD_A)
    arena.claim_prize(0)
    with pytest.raises(Exception):
        arena.claim_prize(0)
    assert arena.get_credit(direct_bob) == 2 * 10**17      # paid exactly once


def test_cannot_claim_without_a_verdict(direct_vm, arena, direct_bob):
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        arena.claim_prize(0)


def test_withdraw_credit_zeroes_before_paying(direct_vm, arena, direct_bob, direct_charlie):
    _judge_for(direct_vm, arena, direct_bob, direct_charlie, GOOD_A)
    arena.claim_prize(0)
    direct_vm.sender = direct_bob
    arena.withdraw_credit()
    assert arena.get_credit(direct_bob) == 0
    with pytest.raises(Exception):
        arena.withdraw_credit()


def test_page_view_reports_totals(direct_vm, arena):
    p = arena.get_page(0, 10)
    assert p["total"] == 1
    assert len(p["rows"]) == 1
    assert p["rows"][0]["evidence_count"] == 0


# ---------------- address arguments arrive as 0x strings over ABI ----------------

def test_create_match_accepts_hex_string_players(
        direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """GenVM passes address arguments as 0x-hex strings, so the contract must parse them."""
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT)
    a_hex = "0x" + direct_bob.hex()
    b_hex = "0x" + direct_charlie.hex()
    direct_vm.value = 10**17
    mid = c.create_match("Hex players", RULES, a_hex, b_hex, 3600)
    direct_vm.value = 0
    m = c.get_match(mid)
    assert m["prize"] == 10**17
    assert m["player_a"].lower().replace("0x", "") == direct_bob.hex().lower().replace("0x", "")
    assert m["player_b"].lower().replace("0x", "") == direct_charlie.hex().lower().replace("0x", "")


def test_create_match_rejects_a_bad_address_string(
        direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT)
    direct_vm.value = 10**17
    with pytest.raises(Exception):
        c.create_match("Bad addr", RULES, "0x1234", "0x" + direct_bob.hex(), 3600)
    direct_vm.value = 0


def test_get_credit_accepts_a_hex_string(
        direct_vm, arena, direct_bob):
    who = "0x" + direct_bob.hex()
    assert arena.get_credit(who) == 0
