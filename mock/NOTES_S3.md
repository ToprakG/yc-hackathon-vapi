# S3 -> S2 (converter status, 19:4x)
- `python3 mock/convert.py --id <id> --customers <xlsx|csv|json|md|docx|pdf> --openapi <openapi.json> --config-from <config.json|seed:A|omit=LLM from contract> [--contract <md|docx|pdf>]` -> `mock/spec.<id>.json`; `--check <spec>` validates.
- Turkish: headers (ad, soyad, ad soyad, müşteri no, doğum tarihi, TC kimlik, telefon (son 4), kart son dört, ürün, ekstre borcu, asgari ödeme, taksit, son ödeme tarihi, gecikme gün...) are mapped offline; any required field not mapped -> LLM column mapping; still missing -> hard failure (no silent drop).
- Formats parsed: dates 14.03.1988 / 14 Mart 1988 / ISO / Excel dates; amounts `1.234,56 TL`, `₺ 12.000`, `1,234.56`; last-4 digits zero-padded; `Arama Zamanı` -> variables.now.
- Product `type` is kept as written in the file; `--check` warns if it is not in config.product_types enums (e.g. "Kredi Kartı" vs credit_card): fix in the spec or the config for the final.
- The Worker reads only the spec JSON (see SPEC.md). Customers are `{customer_id, variables, identity{...}, products[...]}`; identity keys can include `national_id` if the final contract asks for it.
