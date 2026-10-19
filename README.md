# ArenaJudge

**Escrowed prize pools settled by an on-chain referee — built on GenLayer Intelligent Contracts.**

A tournament host has to hold the prize and also decide who won. ArenaJudge separates those roles:
the host escrows the money and writes the rules, and an on-chain jury — not the host — reads both
players' evidence and names the winner.

- **The host escrows the prize and writes the rules** (`create_match`, payable) and names the two
  players. The host cannot also play.
- **Each named player submits one artifact** (`submit_evidence`) — match log, replay, screenshot set.
- **An on-chain jury names the winner** (`judge_match`) — the contract fetches *both* artifacts inside
  the non-deterministic block and rules A / B / draw under the stated rules.
- **The prize is credited to the winner** (`claim_prize`) — a draw splits it.
- **The winner pulls the money themselves** (`withdraw_credit`) — the credit is zeroed before the
  transfer, so a duplicate payout is structurally impossible.
- **If no verdict is reachable, the host gets the prize back** (`refund`).

Every path ends in a real transfer, and no prize can be stranded.

---

## Why this needs GenLayer

Deciding a match is a judgement over prose and screenshots. A classic contract can hold the prize but
cannot open a single artifact, so the decision has to be made off-chain by the same party holding the
money — exactly the arrangement players don't trust.

GenLayer's non-deterministic execution (`gl.nondet.web.get` + `gl.nondet.exec_prompt` under
`gl.vm.run_nondet_unsafe` consensus) lets the contract read both sides and reach a verdict validators
agree on, while the prize custody and the payout stay deterministic and real.

---

## Contract

`contracts/arena_judge.py` — deployed on **Bradbury**.

```
0x37CAC21d02B4805aB25f56355BABe7058Ae6F04B
```

### Money flow

| Step | Call | What moves |
|---|---|---|
| 1 | `create_match(title, rules, player_a, player_b)` — **payable** | Host → contract custody, booked as the match's `prize` |
| 2 | `submit_evidence(match_id, evidence_url)` | No funds move. Either named player, one artifact each |
| 3 | `judge_match(match_id)` | No funds move. `{inconclusive, winner, score, confidence, reason}` |
| 4a | `claim_prize(match_id)` — verdict exists | `credits[winner] += prize` (a draw splits it) |
| 4b | `refund(match_id)` — no verdict | `credits[host] += prize` |
| 5 | `withdraw_credit()` | credit → 0, then one `emit_transfer(value, on='finalized')` |

### Guards

- A prize is required; title and rules are length-bounded; the host cannot also be a player; the two
  players must differ.
- Only the two named players can submit evidence, and only while the match is OPEN.
- Judging requires both artifacts, is bounded to 3 rounds, and a final verdict is one-shot.
- **Unavailable evidence never decides a match.** A fetch failure, a consensus failure or a malformed
  verdict payload moves the match to `INCONCLUSIVE`: nobody is paid, nobody forfeits, and the host can
  refund once the rounds are spent.
- `claim_prize` is idempotent (`settled` is checked before the state) so a repeat call cannot pay twice.
- `withdraw_credit` clears the credit *before* requesting the transfer.
- `refund` is host-only, refuses an existing verdict, and refuses while judging rounds remain (unless
  the match never started).

---

## Repository layout

```
contracts/arena_judge.py           the Intelligent Contract (16,547 bytes)
tests/direct/test_arena_judge.py   24 direct-mode tests
index.html                         web UI — waits for finalization, paginated
genlayer.config.yaml               network configuration (Bradbury default)
```

---

## Run the tests

```bash
pip install genlayer-test
pytest tests/direct/ -v
```

```
24 passed
```

Coverage: creation validation (prize, title/rules bounds, host≠player, players differ), prize
custody, player-only evidence submission plus URL bounds, the both-artifacts requirement, the
one-shot verdict, bounded rounds, **unreachable evidence ⇒ INCONCLUSIVE with no winner**, malformed
verdict payloads, A/B/draw payouts (including the odd-prize split), idempotent `claim_prize`, the
host-only refund path with its round guard, pull-payment accounting (credit cleared before transfer),
pagination and the full match lifecycle.

---

## Frontend behaviour

Receiving a transaction hash is **not** treated as success. The UI waits for `FINALIZED`, requires
`FINISHED_WITH_RETURN`, reports `LEADER_TIMEOUT`/`UNDETERMINED` as an uncertain outcome while keeping
the tx id visible, refreshes contract state after a confirmed success, and paginates via `get_page`.

---

## Deploy

```bash
genlayer network set testnet-bradbury
genlayer deploy --contract contracts/arena_judge.py
```

## Use it

```bash
# 1. host escrows the prize and writes the rules (payable)
genlayer write <CONTRACT> create_match --args "Grand Final" "Best of three; higher final score wins" <playerA> <playerB> --value 0.2

# 2. each player submits one artifact
genlayer write <CONTRACT> submit_evidence --args 1 "https://example.com/a-log"
genlayer write <CONTRACT> submit_evidence --args 1 "https://example.com/b-log"

# 3. the jury decides
genlayer write <CONTRACT> judge_match --args 1

# 4. award, then pull
genlayer write <CONTRACT> claim_prize --args 1
genlayer write <CONTRACT> withdraw_credit

# 5. or, if no verdict was reachable, the host reclaims the prize
genlayer write <CONTRACT> refund --args 1
```

Web UI: open `index.html` — no build step, no dependencies.

---

## Verified on Bradbury

See `_EVIDENCE.md` for the full published run: deployment transaction, exact deployed source size,
the match creation and both evidence submissions, the judging transaction and its verdict, the prize
credit, the winner's withdrawal, and before/after native balances.

---

## License

MIT
