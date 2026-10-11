#!/usr/bin/env python3
"""The bank's service contract (2026-10-01) as an OpenAPI 3 document: seven POST services under <base>/<service>, the {data, call} envelope, the {data, result} answer,
the error shapes and the OAuth2 client-credentials scheme. `{{mock_url}}` in tokenUrl is replaced by the Worker with this tenant's base.
    python3 mock/final/build_openapi.py [-o mock/final/bank.openapi.json]
"""
import argparse, json, pathlib

S = lambda **k: {"type": "string", **k}
N = lambda **k: {"type": "number", **k}
I = lambda **k: {"type": "integer", **k}
O = lambda props, req=None, **k: {"type": "object", "properties": props, **({"required": req} if req else {}), **k}
ANY_NUM_STR = {"oneOf": [{"type": "integer"}, {"type": "string"}]}

CALL = O({"ani": S(description="the caller's number"), "lang": S(description="language, 'tr'")}, description="Call metadata, logged by the bank; nothing depends on it.")
RESULT = O({"guid": S(description="trace id; give it when opening a ticket"), "returnCode": S(description="'1' = success; otherwise an error code"), "messageText": S(description="for logs, never read to the caller"),
            "code": S(description="same value as returnCode"), "message": S(description="same as messageText"), "type": {"type": ["string", "null"], "enum": ["ERROR", "WARNING", None]},
            "details": O({"guid": S(), "rootCause": {"type": ["string", "null"]}, "errorOrigin": {"type": ["string", "null"]}})},
           description="Present in every answer. Success = HTTP 200 and returnCode '1'.")
ERR = O({"result": RESULT}, description="Error answer: no `data`, only `result` (code, type ERROR|WARNING).")
CUR = O({"statementPaymentStatus": S(enum=["HAS_DEBT", "NO_DEBT"]), "transferAmount": N(), "statementDebt": N(description="statement debt"), "minPayment": N(description="minimum payment on the statement"),
         "remainingDebt": N(description="statement debt left after payments"), "remainingMinPayment": N(description="minimum payment left"), "currentPeriodExpense": N(description="spending after the statement"),
         "totalDebt": N(description="includes spending after the statement; negative = credit balance (status NO_DEBT)"), "totalDebtPaymentStatus": S(enum=["HAS_DEBT", "NO_DEBT"]), "remainAutomaticPaymentAmount": N(description="only meaningful when automaticPaymentFlag is 'Y'")},
        description="One currency. The whole block can be MISSING for a currency (not the same as NO_DEBT): never invent zeros.")


def op(name, summary, desc, req, resp, errors):
    envelope = O({"data": O(req["props"], req.get("required")), "call": CALL}, ["data"])
    ok = O({"data": O(resp, description="Service fields."), "result": RESULT}, ["data", "result"])
    responses = {"200": {"description": "Success (HTTP 200 and result.returnCode '1').", "content": {"application/json": {"schema": ok}}}}
    for code, d in errors.items():
        responses[code] = {"description": d, "content": {"application/json": {"schema": ERR}}}
    return {"post": {"operationId": name, "summary": summary, "description": desc, "security": [{"bankOAuth": ["voice.statement"]}],
                     "requestBody": {"required": True, "content": {"application/json": {"schema": envelope}}}, "responses": responses}}


E400 = "A required field is missing or empty: result.code INVALID_ARGUMENTS_ERROR, message names the field."
E500 = "Technical error: result.code FBE00099 (type ERROR). The call may be repeated except for the two services with side effects (statement.week.change, statement.pdf.send): no automatic retry there."
E401 = "Token missing or expired (not checked in the test environment): get a new token and retry once."

paths = {
    "/cards.list": op("cards.list", "The customer's cards the assistant may talk about",
        "Start here: the phone menu hands over the customer number, there is no customer search. Only active cards (status 'A') come back; isMainCard=false for a card that is not the customer's own main card, still listed. "
        "Two cards can share productName AND cardNumberLast4 - do not assume the last four are unique. cardNumber is masked in test (first 6, last 4); send it unchanged to the other services.",
        {"props": {"customerNo": {**ANY_NUM_STR, "description": "8-digit customer number; string or number"}, "aiFlow": S(description="use case; 'CardOps' for this one (not validated in test)")}, "required": ["customerNo"]},
        {"cards": {"type": "array", "items": O({"cardNumber": S(description="exactly this value goes into the other services"), "cardNumberLast4": S(), "productName": S(description="free text from the card system"), "status": S(enum=["A"]), "isMainCard": {"type": "boolean"}})},
         "validCardsCount": I(), "exitState": S(enum=["1_CARD", "MULTI_CARD"])},
        {"400": E400, "401": E401, "404": "FB_IVR_CHANNEL_102 (WARNING): the customer has no valid card. Not a service failure, different from a 500.", "500": E500}),
    "/cards.balance": op("cards.balance", "Statement and due dates, debt per currency for one card",
        "Send cardNumber exactly as cards.list returned it. The answer's own cardNumber is masked differently (first 4 + last 4): do not match it against the list, use cardNumberLast4 or keep the number you sent. "
        "Dates dd.MM.yyyy, amounts are numbers (dot decimal, never rounded). debtTL/debtUSD/debtEUR/debtGBP: a block can be missing.",
        {"props": {"cardNumber": S()}, "required": ["cardNumber"]},
        {"cardNumber": S(), "cardNumberLast4": S(), "productName": S(), "statementDate": S(description="last issued statement, dd.MM.yyyy"), "lastPayDate": S(description="its due date, dd.MM.yyyy"),
         "nextStatementDate": S(), "nextLastPayDate": S(), "debtTL": CUR, "debtUSD": CUR, "debtEUR": CUR, "debtGBP": CUR, "statementPaymentStatus": S(enum=["HAS_DEBT", "NO_DEBT"]),
         "totalDebtPaymentStatus": S(enum=["HAS_DEBT", "NO_DEBT"]), "automaticPaymentFlag": S(enum=["Y", "N"])},
        {"400": E400, "401": E401, "404": "FB_IVR_CHANNEL_120 (WARNING): card not found.", "500": E500}),
    "/statement.week.get": op("statement.week.get", "The card's current statement week and day, joint statement info",
        "statementWeek 1-4 and statementDay are numbers here. relationType '' = own statement; 'M' = main card of a pair sharing one statement, 'C' = the linked card; relatedCardNumber/relatedCardProductName name the other card. "
        "Changing the week on either card moves both. No field says whether the customer may still change the week.",
        {"props": {"cardNumber": S()}, "required": ["cardNumber"]},
        {"cardNumber": S(), "cardNumberLast4": S(), "productName": S(), "statementWeek": I(), "statementDay": I(), "statementDate": S(), "lastPayDate": S(), "nextStatementDate": S(), "nextLastPayDate": S(),
         "relationType": S(enum=["", "M", "C"]), "relatedCardNumber": S(), "relatedCardProductName": S()},
        {"400": E400, "401": E401, "404": "FB_IVR_CHANNEL_121 (WARNING): card not found.", "500": E500}),
    "/statement.week.decide": op("statement.week.decide", "Preview the dates a new statement week would give (changes nothing)",
        "newStatementWeek 1-4 (number or string). statementDay = the card's current statementDay from statement.week.get. Do not call it for the week the card already has (error). "
        "The due date is called statementDueDate here (not lastPayDate).",
        {"props": {"cardNumber": S(), "newStatementWeek": {**ANY_NUM_STR, "description": "1-4"}, "statementDay": I(description="current statementDay")}, "required": ["cardNumber", "newStatementWeek", "statementDay"]},
        {"statementDate": S(description="dd.MM.yyyy"), "statementDueDate": S(description="dd.MM.yyyy"), "statementDay": I(), "responseCode": I(description="0 = fine"), "responseMessage": S()},
        {"400": E400, "401": E401, "500": E500}),
    "/statement.week.change": op("statement.week.change", "Change the card's statement week (side effect)",
        "Call only after the caller agreed to the dates from statement.week.decide. statementDay is required (send the current day). NOTE: statementWeek and statementDay come back as STRINGS here; ignore statementDay in the answer and "
        "tell the caller the dates from decide. Success = exitState 'OK' and responseCode 0. No automatic retry.",
        {"props": {"cardNumber": S(), "newStatementWeek": {**ANY_NUM_STR, "description": "1-4"}, "statementDay": I(description="current statementDay")}, "required": ["cardNumber", "newStatementWeek", "statementDay"]},
        {"responseCode": I(), "responseMessage": S(), "statementWeek": S(), "statementDay": S(), "exitState": S(enum=["OK"])},
        {"400": E400, "401": E401, "500": E500}),
    "/contact.email.get": op("contact.email.get", "The registered e-mail / phone of the customer",
        "intAddressInfoType: 'E' e-mail, 'P' phone, 'B' both (empty = 400). The registered e-mail is ibanEmail (the iban prefix is historical); ttsEmail is the same prepared for reading aloud. "
        "No registered e-mail = communicationType 'Phone' and/or empty ibanEmail: check the field, not only the type.",
        {"props": {"customerNo": {**ANY_NUM_STR}, "intAddressInfoType": S(enum=["E", "P", "B"])}, "required": ["customerNo", "intAddressInfoType"]},
        {"communicationType": S(), "ibanCountryCode": S(), "ibanAreaCode": S(), "ibanPhoneNum": S(), "ibanEmail": S(description="registered e-mail, '' if none"), "ttsEmail": S(), "commGramType": S(), "exitState": S()},
        {"400": E400, "401": E401, "500": E500}),
    "/statement.pdf.send": op("statement.pdf.send", "E-mail the statement PDF (side effect)",
        "The backend sends to whatever is in emailAddress and does NOT check it against the registered address (a business rule for the assistant). statementDate = statementDate from cards.balance. "
        "currencyType TL|USD|EUR|GBP. No automatic retry.",
        {"props": {"customerNo": ANY_NUM_STR, "cardNumber": S(), "currencyType": S(enum=["TL", "USD", "EUR", "GBP"]), "statementDate": S(description="dd.MM.yyyy"), "emailAddress": S()},
         "required": ["customerNo", "cardNumber", "currencyType", "statementDate", "emailAddress"]},
        {"exitState": S(enum=["DONE"])},
        {"400": E400, "401": E401, "404": "FB_IVR_CHANNEL_107 (WARNING): no PDF for that statement.", "500": E500}),
}

doc = {"openapi": "3.0.3",
       "info": {"title": "Freya Bank voice statement services", "version": "2026-10-01",
                "description": "Seven POST services, JSON in/out, UTF-8. Request {data, call}; answer {data, result}. Dates dd.MM.yyyy, amounts JSON numbers. Get a bearer token first (client-credentials at tokenUrl; the test environment does not check it, send it anyway). Service names contain dots."},
       "servers": [{"url": "https://api.freyabank.example/voice/v1"}],
       "components": {"securitySchemes": {"bankOAuth": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "{{mock_url}}/oauth2/token", "scopes": {"voice.statement": "statement services"}}}}}},
       "security": [{"bankOAuth": ["voice.statement"]}],
       "paths": paths}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("-o", default=str(pathlib.Path(__file__).with_name("bank.openapi.json")))
    a = ap.parse_args(); json.dump(doc, open(a.o, "w"), ensure_ascii=False, indent=1); print(a.o, len(paths), "paths")
