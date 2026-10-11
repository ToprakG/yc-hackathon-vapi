# Language of the workflow

The workflow speaks the language of the brief documents. Decide it once, in step 1, and write `policy.language` (ISO code, detected from the brief
text; `en` when the brief is English). Everything below follows from that one value.

## What must be in that language

Everything the agent says or reads as an instruction, nothing left in English because the skill's examples are English (the texts in
`templates/fragments/*.json` and in the pattern demo are English placeholders: translate them when you copy a fragment):

- `system_prompt` (identity, tone, honesty rules, forbidden words) and **every node prompt** (`task_message`, `loop_prompt`, ...).
- Every static line: `on_enter` tts texts, a terminal `spoken_message`, the opening, the goodbye, the robot / scam / failed-identity answers.
- Every sentence that **code** builds and the agent then says (`vars['say']`, read-backs, offers, "which day exactly", "that is not a business day",
  retry lines, fallbacks in the `except` branch). Hook `what_to_do_next` texts too: the model reads them and says what they say.
- Sentences the brief fixes are copied **verbatim** and are never translated or reworded.
- Dates and amounts the way the language writes them (see below).
- Extraction field descriptions may stay in the skill's wording, but enum values stay exactly as the tool API spells them. Keep JSON keys, variable
  names and tool names in English / as the API has them.

`lint_workflow` checks this when `out/policy.json` has a `language` other than `en`: a system prompt, a fixed tts line or a sentence in a code node
that is mostly English function words is an **error**; a node prompt is a **warning**. Fix those before you finish.

## Dates and amounts

- `templates/calendar.py` has `spoken_date_in(d, lang)` (names of weekdays and months per language, day-month-weekday order outside English) and
  `money_say(amount, lang, currency)` (decimal comma / thousands dot or the language's own style; a whole amount has no decimals).
  Add a language to `NAMES` when it is missing.
- The currency is whatever the brief writes next to amounts. Write it to `policy.currency` verbatim (symbol or word, `null` when the brief names none)
  and pass it to `money_say`. Never add a currency the brief does not use.
- Amounts and dates **sent to a tool** stay plain (`1234.5`, `YYYY-MM-DD`, cents when the API says so); only spoken text is formatted.
- Say the form of address the language needs (a title after the surname, a formal "you") as the brief states it.

## What the customer says

The customer speaks the same language. The number and date parsers in `calendar.py` read English words. For another language:

- Prefer extracting the customer's words as said and converting them in a code node with a **normalizer for that language** before parsing. For
  Turkish paste `templates/tr_speech.py` (`tr_norm`) and call it on the extracted text first; it covers number words, month and weekday words, suffixed
  and ordinal forms, "buçuk" / "yarım", decimal comma and thousands dot.
- For any other language write the same small mapping (number words, month names, weekday names, "today" / "tomorrow", the currency words the
  brief uses) rather than relying on the English tables. Never rewrite a free-text answer (a name, a code word) this way.
- A model-extracted value that is already a digit string or an ISO date must pass through unchanged; a parser that returns nothing must never
  override or reject a correct extracted value.

## Platform note

Freya may speak its own filler line in the account's default language when a node's `on_enter` asks the model to call a tool first (see
`platform-facts.md`). Use a static tts line or a silent code step before tools so no filler line is spoken.
