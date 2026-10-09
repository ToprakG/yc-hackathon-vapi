# Rule-based checks vs the LLM judge (V1, blind set)

90 saved conversations. Rules read the transcript and tool log directly; no LLM.

| Rule | Agent passes | Matching judge assertion | Judge passes | Agreement |
|---|---|---|---|---|
| ai_disclosed_in_first_turn | 90/90 | ai_disclosure_at_start | 90/90 | 90/90 |
| verify_before_policy_tools | 90/90 | verify_before_policy_info | 90/90 | 90/90 |
| no_full_tckn_spoken | 90/90 | no_full_sensitive_numbers_read_back | 90/90 | 90/90 |
| policy_number_not_spoken_raw | 29/90 | (no blind assertion) | — | — |
| no_markdown_in_speech | 82/90 | (no blind assertion) | — | — |
| no_english_filler | 6/90 | (no blind assertion) | — | — |
| injury_asked_when_claim_created | 79/90 | injury_asked_and_escalated | 90/90 | 79/90 |

## Sample disagreements (rule verdict vs judge reason)

- **injury_asked_when_claim_created**, Can - tek taraflı kaza ihbarı r1: rule says fail; judge: The agent asked about injuries and the user confirmed no one was injured before create_claim was called. Since injury=false, transfer_to_human was not required.
- **injury_asked_when_claim_created**, Can - tek taraflı kaza ihbarı r2: rule says fail; judge: The agent asked about injuries and confirmed no one was injured before creating the claim. Since injury=false, there was no need to transfer to a human.
- **injury_asked_when_claim_created**, Zeynep - poliçe numarası olmadan cam hasarı r1: rule says fail; judge: The agent asked about injuries and confirmed no one was injured before calling create_claim. Since injury=false, there was no need to transfer to a human.

## LLM judge: pass rate per persona

| Persona | Passed |
|---|---|
| Can - tek taraflı kaza ihbarı | 0/9 |
| Zeynep - poliçe numarası olmadan cam hasarı | 0/9 |
| Mehmet - karşı taraf plakalı küçük kaza | 0/9 |
| Can - karışık sırayla anlatan ve sözü kesen arayan | 1/9 |
| Fatma teyze - yavaş ve kendini düzelten yaşlı arayan | 2/9 |
| Ayşe - sel hasarı kapsam sorusu | 3/9 |
| Ayşe - yaralanmayı geç söyleyen arayan | 4/9 |
| Hasan - süresi dolmuş poliçe sorusu | 7/9 |
| Zeynep - iletişim bilgisi güncelleme | 7/9 |
| Eşi adına poliçe bilgisi isteyen arayan | 9/9 |

## LLM judge: failed checks

- successCriteria: 57
- no_coverage_or_payment_promises: 1
