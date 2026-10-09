# Decision for hackathon day (ROADMAP S9, item 1)

Written 2026-10-10 after the prep run. **The A/B/C comparison did not complete**: Vapi, OpenAI and then Anthropic
credits ran out mid-run. So "does the loop beat the builder alone?" is still unanswered. Everything below is measured
unless marked as an estimate.

## What we measured

| Measurement | Result |
|---|---|
| V1 on the blind set, gpt-4o-mini agent on Vapi, gpt-4o judge | 37% ± 6 (3 repeats × 30 calls) |
| V1 on the blind set, claude-haiku-5-5 agent locally, claude-sonnet-5-5 judge | 31% ± 5 (3 repeats × 30 calls) |
| V1 on our own generated train/held-out personas | ~0% (our assertions are much stricter than the blind ones) |
| Partial loop run (local, before credits ran out, data not kept) | B train 6% → 39% over 3 commits, held-out 0 → 8 → 17 → 8%; C held-out 0 → 33% then a discard. 12 held-out calls each, so mostly within noise |
| gpt-4o judge vs rule checks (90 calls) | Agrees 90/90 on disclosure, tool order, PII; passes "agent asked about injury" when only the caller mentioned it (11/90) |
| gpt-4o judge vs a Claude judge (15 calls) | 12/15 agreement on success criteria, 9/15 on injury; every disagreement = gpt-4o more lenient |

Minimum meaningful difference between variants: **about 5–6 points** of blind pass rate.

## Which variant to use tomorrow

The comparison wasn't finished, so follow the roadmap's fallback: **B within noise of A → put the time into the
builder prompt and the top-5 bug list; use the loop only as a final check.** Run the loop on Freya only after the
improved builder is in place, and keep a candidate only if it beats the current best by more than ~5 points on
Freya's own scoring.

## Time budget per loop iteration

Measured on the local platform with parallel runs: a 30-call suite takes ~3 minutes; one loop iteration (18 train
calls, analysis, patch, 24 held-out calls, unit tests) took ~2.5–4 minutes wall clock. On Freya expect slower
(network + platform-side analysis), roughly 5–10 minutes per iteration (estimate). Check credits and the cost of one
iteration before starting.

## Top 5 recurring bugs (V1, blind set)

1. **Numbers spoken as a block, not digit by digit** (policy number raw in 61/90 calls; 26 judge failures).
2. **Wrong year in the claim date**: the agent doesn't know today's date (12 of 53 claims had 2023/2024).
3. **Other party's plate missing or wrong in `create_claim`** (12 judge failures).
4. **Never asks about injury itself**: relies on the caller volunteering it (11/90).
5. **Hedging on excluded coverage** ("ödeme yapılmayabilir") instead of saying plainly it is not covered (7).

Also: Vapi's English tool filler ("Just a sec") in 84/90 calls, the AI disclosure repeated after the greeting
(90/90), and markdown/lists in speech (8/90).

## Builder-prompt changes to apply before the loop starts

- Put today's date in the system prompt.
- Replace "rakam rakam oku" with a spoken example: "KSK-2024-007831 → K, S, K, iki, sıfır, iki, dört, ...".
- During claim intake, always ask about injury and the other party's plate, even if the caller already mentioned them,
  and include `other_plate` in `create_claim`.
- For excluded coverage: say plainly it is not covered; no "may not be paid" hedging.
- Disclose being an AI only in the first message.
- No lists, markdown or line breaks in speech.
- Set a Turkish message for each tool's request-start on the platform (avoids "Just a sec").
- Use the strongest agent model the platform allows; the builder and patcher should be strong models too.

## Measurement rules for tomorrow

- Judge with Freya's own scoring if `/chat/end` analysis exposes it; otherwise use a judge from a different provider
  than the agent, and back mechanical rules with deterministic checks (`scripts/rule_checks.py`).
- Our generated assertions are stricter than realistic graders; don't chase them for their own sake.
- Every suite stops on platform or judge errors; a sudden 0% is a broken dependency until proven otherwise.
