# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from dataclasses import dataclass
from genlayer import *

MAX_TITLE = 96
MAX_RULES = 700
MAX_URL = 512
MAX_REASON = 500
MAX_ROUNDS = 3
EVIDENCE_CHARS = 5000
SCORE_TOLERANCE = 10

S_OPEN = u8(0)
S_JUDGED = u8(1)
S_INCONCLUSIVE = u8(2)
S_PAID = u8(3)
S_REFUNDED = u8(4)


@allow_storage
@dataclass
class Match:
    host: Address
    title: str
    rules: str
    prize: u256
    player_a: Address
    player_b: Address
    evidence_a: str
    evidence_b: str
    winner: u8              # 0 = undecided, 1 = A, 2 = B, 3 = draw
    state: u8               # 0 OPEN 1 JUDGED 2 INCONCLUSIVE 3 PAID 4 REFUNDED
    rounds: u256
    reason: str
    confidence: str
    settled: bool


@gl.evm.contract_interface
class _Payee:
    class View:
        pass

    class Write:
        pass


class ArenaJudge(gl.Contract):
    """Escrowed prize pools settled by an on-chain jury reading both players' match evidence.

    A tournament host escrows the prize and writes the rules. The two players each submit the
    artifact that proves their side (match log, replay, screenshot set). A jury then fetches both
    artifacts and names the winner under the stated rules; the winner claims the prize.

    Safety properties carried over from earlier review rounds:

    * **Unavailable evidence is never a loss.** If a source cannot be fetched, or the jury cannot
      agree on a well-formed verdict, the match becomes INCONCLUSIVE: nobody is paid and nobody
      forfeits. Hosts can retry (bounded) or refund themselves.
    * **Prize moves by pull.** Judging only credits the winner inside the contract; the winner calls
      ``withdraw_credit`` themselves. No entitlement is extinguished by a transfer the contract
      cannot observe, and a duplicated payout is structurally impossible.
    * **Strict validator agreement** on the winner, the confidence label and the score.
    """

    matches: TreeMap[u256, Match]
    credits: TreeMap[str, u256]
    next_id: u256

    def __init__(self):
        self.next_id = u256(1)

    # -------------------------------------------------------- internals ----

    def _to_addr(self, value) -> Address:
        if isinstance(value, Address):
            return value
        return Address(value)

    def _addr_bytes(self, value) -> bytes:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        for attr in ("as_bytes", "_as_bytes", "to_bytes"):
            fn = getattr(value, attr, None)
            if callable(fn):
                try:
                    r = fn()
                    if isinstance(r, (bytes, bytearray)):
                        return bytes(r)
                except Exception:
                    pass
        try:
            return bytes(self._to_addr(value))
        except Exception:
            pass
        s = str(value)
        if s.startswith("0x"):
            try:
                return bytes.fromhex(s[2:])
            except Exception:
                pass
        raise gl.vm.UserError("Unsupported address value")

    def _key(self, value) -> str:
        return self._addr_bytes(value).hex()

    def _match(self, match_id: u256):
        if match_id not in self.matches:
            raise gl.vm.UserError("Match not found")
        return self.matches[match_id]

    def _credit(self, to: Address, amount: u256):
        if int(amount) <= 0:
            return
        k = self._key(to)
        cur = u256(0)
        if k in self.credits:
            cur = self.credits[k]
        self.credits[k] = cur + amount

    def _pay(self, to: Address, amount: u256):
        if int(amount) <= 0:
            return
        _Payee(to).emit_transfer(value=u256(amount), on='finalized')

    # ------------------------------------------------------------- views ----

    @gl.public.view
    def get_match(self, match_id: u256) -> dict:
        m = self.matches[match_id]
        return {
            "id": match_id,
            "host": "0x" + self._key(m.host),
            "title": m.title,
            "rules": m.rules,
            "prize": m.prize,
            "player_a": "0x" + self._key(m.player_a),
            "player_b": "0x" + self._key(m.player_b),
            "evidence_a": m.evidence_a,
            "evidence_b": m.evidence_b,
            "winner": m.winner,
            "state": m.state,
            "rounds": m.rounds,
            "reason": m.reason,
            "confidence": m.confidence,
            "settled": m.settled,
        }

    @gl.public.view
    def get_match_count(self) -> u256:
        return self.next_id - u256(1)

    @gl.public.view
    def get_credit(self, who: Address) -> u256:
        k = self._key(who)
        if k not in self.credits:
            return u256(0)
        return self.credits[k]

    @gl.public.view
    def get_page(self, offset: u256, limit: u256) -> dict:
        total = int(self.next_id - u256(1))
        start = int(offset)
        want = int(limit)
        if want <= 0:
            want = 10
        if want > 50:
            want = 50
        out = []
        i = start + 1
        while i <= start + want and i <= total:
            m = self.matches[u256(i)]
            out.append({
                "id": u256(i),
                "title": m.title,
                "prize": m.prize,
                "state": m.state,
                "winner": m.winner,
            })
            i += 1
        return {"total": u256(total), "offset": u256(start), "items": out}

    @gl.public.view
    def get_contract_balance(self) -> u256:
        return self.balance

    # ------------------------------------------------------------ writes ----

    @gl.public.write.payable
    def create_match(self, title: str, rules: str, player_a: Address, player_b: Address) -> u256:
        """Host escrows the prize and names the two players."""
        prize = gl.message.value
        if int(prize) <= 0:
            raise gl.vm.UserError("A prize is required: send GEN with the call")
        t = title.strip()
        r = rules.strip()
        if len(t) == 0:
            raise gl.vm.UserError("Title is required")
        if len(t) > MAX_TITLE:
            raise gl.vm.UserError("Title is too long")
        if len(r) == 0:
            raise gl.vm.UserError("Rules are required")
        if len(r) > MAX_RULES:
            raise gl.vm.UserError("Rules are too long")

        host = self._to_addr(gl.message.sender_address)
        a = self._to_addr(player_a)
        b = self._to_addr(player_b)
        if self._addr_bytes(a) == self._addr_bytes(b):
            raise gl.vm.UserError("The two players must differ")
        if self._addr_bytes(a) == self._addr_bytes(host) or self._addr_bytes(b) == self._addr_bytes(host):
            raise gl.vm.UserError("The host cannot also play")

        m = Match(
            host=host,
            title=t,
            rules=r,
            prize=prize,
            player_a=a,
            player_b=b,
            evidence_a="",
            evidence_b="",
            winner=u8(0),
            state=S_OPEN,
            rounds=u256(0),
            reason="",
            confidence="",
            settled=False,
        )
        mid = self.next_id
        self.matches[mid] = m
        self.next_id = mid + u256(1)
        return mid

    @gl.public.write
    def submit_evidence(self, match_id: u256, evidence_url: str):
        """Either named player submits their side's artifact."""
        m = self._match(match_id)
        if int(m.state) != 0:
            raise gl.vm.UserError("Match is not open for evidence")
        sender = self._key(gl.message.sender_address)
        if sender == self._key(m.player_a):
            slot = "a"
        elif sender == self._key(m.player_b):
            slot = "b"
        else:
            raise gl.vm.UserError("Only the two named players can submit evidence")

        u = evidence_url.strip()
        if len(u) == 0 or not (u.startswith("http://") or u.startswith("https://")):
            raise gl.vm.UserError("A valid evidence URL is required")
        if len(u) > MAX_URL:
            raise gl.vm.UserError("Evidence URL is too long")

        if slot == "a":
            m.evidence_a = u
        else:
            m.evidence_b = u

    @gl.public.write
    def judge_match(self, match_id: u256):
        """The jury reads both artifacts and names the winner under the stated rules."""
        m = self._match(match_id)
        if int(m.state) in (1, 3, 4):
            raise gl.vm.UserError("Match already has a verdict")
        if int(m.rounds) >= int(MAX_ROUNDS):
            raise gl.vm.UserError("Judging rounds exhausted; refund instead")
        if len(str(m.evidence_a).strip()) == 0 or len(str(m.evidence_b).strip()) == 0:
            raise gl.vm.UserError("Both players must submit evidence first")

        title_mem = str(m.title)
        rules_mem = str(m.rules)
        url_a = str(m.evidence_a)
        url_b = str(m.evidence_b)

        def _fetch(url: str) -> tuple:
            try:
                resp = gl.nondet.web.get(url)
                if isinstance(resp, bytes):
                    raw = resp.decode("utf-8", errors="ignore")
                elif hasattr(resp, "body"):
                    raw = resp.body.decode("utf-8", errors="ignore")
                else:
                    raw = str(resp)
                txt = " ".join(raw.split())
                if len(txt) == 0:
                    return ("", False)
                return (txt[:EVIDENCE_CHARS], True)
            except Exception:
                return ("", False)

        def leader_fn():
            page_a, ok_a = _fetch(url_a)
            page_b, ok_b = _fetch(url_b)
            if not ok_a or not ok_b:
                which = "A" if not ok_a else "B"
                return {
                    "inconclusive": True,
                    "winner": "none",
                    "score": 0,
                    "confidence": "low",
                    "reason": "Evidence for player " + which + " could not be retrieved.",
                }
            prompt = (
                "You are the referee of an on-chain match. Decide the winner ONLY from the two "
                "artifacts below and the stated rules.\n\n"
                "MATCH: " + title_mem + "\n"
                "RULES: " + rules_mem + "\n\n"
                "PLAYER A REPORT (" + url_a + "):\n" + page_a + "\n\n"
                "PLAYER B REPORT (" + url_b + "):\n" + page_b + "\n\n"
                "Rules of judgement:\n"
                "1. Prefer independently checkable artifacts (match logs with timestamps, score "
                "boards, replay hashes, third-party records). Unverifiable self-claims supported by "
                "nothing are weak evidence.\n"
                "2. If both sides are supported, weigh which artifact evidences the outcome under "
                "the stated rules more completely.\n"
                "3. Return winner \"draw\" when the artifacts are genuinely equivalent under the rules.\n"
                "4. Use inconclusive ONLY when the artifacts cannot be interpreted at all.\n\n"
                'Respond as JSON with exactly these keys:\n'
                '- "inconclusive": boolean\n'
                '- "winner": "A" | "B" | "draw"\n'
                '- "score": integer 0-100 confidence in the decision\n'
                '- "confidence": "high" | "medium" | "low"\n'
                '- "reason": 2-4 sentences citing both artifacts'
            )
            return gl.nondet.exec_prompt(prompt, response_format='json')

        def _bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() == "true"
            return bool(v)

        def _int(v):
            try:
                return int(v)
            except Exception:
                return None

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            cd = leaders_res.calldata
            if not isinstance(cd, dict):
                return False
            for key in ("inconclusive", "winner", "score", "confidence", "reason"):
                if key not in cd:
                    return False
            if cd.get("confidence") not in ("high", "medium", "low"):
                return False
            if _int(cd.get("score")) is None:
                return False
            if str(cd.get("winner")) not in ("A", "B", "draw", "none"):
                return False

            mine = leader_fn()
            if not isinstance(mine, dict):
                return False
            if _bool(mine.get("inconclusive")) != _bool(cd.get("inconclusive")):
                return False
            if str(mine.get("winner")) != str(cd.get("winner")):
                return False
            if str(mine.get("confidence")) != str(cd.get("confidence")):
                return False
            ms = _int(mine.get("score"))
            cs = _int(cd.get("score"))
            if ms is None or cs is None or abs(ms - cs) > SCORE_TOLERANCE:
                return False
            return True

        try:
            result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        except Exception:
            m.state = S_INCONCLUSIVE
            m.rounds = m.rounds + u256(1)
            m.reason = "Validators could not agree; no prize was awarded."
            m.confidence = "low"
            return

        m.rounds = m.rounds + u256(1)

        if not isinstance(result, dict) or "winner" not in result or "inconclusive" not in result:
            m.state = S_INCONCLUSIVE
            m.reason = "Malformed verdict payload; no prize was awarded."
            m.confidence = "low"
            return

        if _bool(result.get("inconclusive")):
            m.state = S_INCONCLUSIVE
            m.reason = str(result.get("reason", "Evidence unavailable."))[:MAX_REASON]
            m.confidence = str(result.get("confidence", "low"))
            return

        w = str(result.get("winner"))
        if w == "A":
            m.winner = u8(1)
        elif w == "B":
            m.winner = u8(2)
        elif w == "draw":
            m.winner = u8(3)
        else:
            m.state = S_INCONCLUSIVE
            m.reason = "Unrecognised winner label; no prize was awarded."
            m.confidence = "low"
            return

        m.state = S_JUDGED
        m.confidence = str(result.get("confidence", ""))
        m.reason = str(result.get("reason", ""))[:MAX_REASON]

    @gl.public.write
    def claim_prize(self, match_id: u256):
        """Credit the prize to the winner (or split it on a draw). Pull, never push."""
        m = self._match(match_id)
        if m.settled:
            raise gl.vm.UserError("Prize already settled")
        if int(m.state) != 1:
            raise gl.vm.UserError("Match has no final verdict")

        m.settled = True
        m.state = S_PAID
        prize = int(m.prize)

        if int(m.winner) == 1:
            self._credit(m.player_a, u256(prize))
        elif int(m.winner) == 2:
            self._credit(m.player_b, u256(prize))
        else:
            half = prize // 2
            self._credit(m.player_a, u256(half))
            self._credit(m.player_b, u256(prize - half))

    @gl.public.write
    def refund(self, match_id: u256):
        """The host reclaims the prize when no verdict could be reached."""
        m = self._match(match_id)
        if m.settled:
            raise gl.vm.UserError("Prize already settled")
        if self._key(gl.message.sender_address) != self._key(m.host):
            raise gl.vm.UserError("Only the host can refund")
        if int(m.state) == 1:
            raise gl.vm.UserError("A verdict exists; claim it instead")
        if int(m.state) == 2 and int(m.rounds) < int(MAX_ROUNDS):
            raise gl.vm.UserError("Judging rounds remain; retry first")
        # S_OPEN is refundable: nobody played yet, so the host reclaims the escrow

        m.settled = True
        m.state = S_REFUNDED
        self._credit(m.host, m.prize)

    @gl.public.write
    def withdraw_credit(self):
        me = self._to_addr(gl.message.sender_address)
        k = self._key(me)
        if k not in self.credits:
            raise gl.vm.UserError("No credit to withdraw")
        amt = self.credits[k]
        if int(amt) <= 0:
            raise gl.vm.UserError("No credit to withdraw")
        self.credits[k] = u256(0)
        self._pay(me, amt)
