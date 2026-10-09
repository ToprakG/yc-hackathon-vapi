# Judge check and V1 blind-set analysis (offline, 2026-10-09)

Data: V1's 90 saved blind-set conversations (3 noise repeats × 10 personas × 3 runs), judged at the time by
`openai:gpt-4o`. No new conversations; Vapi and OpenAI credits were exhausted. Consistency (re-scoring the same
transcript) could not be measured for the same reason.

## Is the judge trustworthy?

**Rule-based checks vs judge (90 conversations, `scripts/rule_checks.py`):**

| Check | Agreement |
|---|---|
| AI disclosed in first turn | 90/90 |
| verify_identity before get_policy/create_claim | 90/90 |
| No full TCKN spoken | 90/90 |
| Agent asked about injury when filing a claim | **79/90**: the judge passed all 90; in 11 the caller volunteered "kimse yaralanmadı" and the agent never asked |

**Second judge from another provider (Claude, 15 conversations, blind to gpt-4o's verdicts):**

| Check | gpt-4o passes | Claude passes | Agreement |
|---|---|---|---|
| Persona successCriteria | 5/15 | 2/15 | 12/15 |
| Injury assertion | 15/15 | 9/15 | **9/15** |

Verdict: the judge is reliable on mechanical rules (tool order, disclosure, PII). It is **lenient on "did the agent
do X" when the caller did X**, and every disagreement went the same way (gpt-4o passes, Claude fails). Same-provider
leniency is plausible (gpt-4o judging gpt-4o-mini). Expect our measured pass rates to be optimistic.

## What V1 actually gets wrong (57 of 90 runs fail successCriteria)

| Bug | Runs | Source |
|---|---|---|
| English tool filler ("Just a sec", "Give me a moment") | 84/90 | rule check (Vapi default tool messages) |
| Repeats "ben yapay zeka asistanıyım" after the first message | 90/90 | rule check |
| Policy/claim number spoken as a block, not digit by digit | 61/90 raw policy number; 26 judge failures | rule + judge |
| Wrong year in create_claim date (agent doesn't know today's date) | 12/53 claims (2023/2024 instead of 2026) | tool log |
| other_plate missing or wrong in create_claim | 12 judge failures | judge |
| Never asks about injury itself | 11/90 | rule check |
| Hedging on excluded coverage ("ödeme yapılmayabilir") | 7 | judge |
| Markdown / lists in speech | 8/90 | rule check |

Per persona (LLM judge): ordinary claim callers fail most (Can, Zeynep, Mehmet: 0/9). The social-engineering caller
passes 9/9. Since hidden benchmarks are mostly ordinary callers, the basic claim flow is where points are lost.
