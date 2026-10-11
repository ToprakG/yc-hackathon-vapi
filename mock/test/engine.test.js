import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { Bank, openapi } from "../src/engine.js";

const spec = JSON.parse(fs.readFileSync(new URL("../specs/brief-a.json", import.meta.url)));
function mem() {
  const m = new Map();
  return { get: async (k) => (m.has(k) ? structuredClone(m.get(k)) : undefined), put: async (k, v) => void m.set(k, structuredClone(v)), delete: async (k) => void m.delete(k),
    list: async (p) => [...m.entries()].filter(([k]) => k.startsWith(p)).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => [k, structuredClone(v)]) };
}
const cid = spec.customers[0].customer_id, id = spec.customers[0].identity;
const call = (b, p, body, h) => b.call("POST", "/v1/" + p, body, h);
const verified = async (b) => { await call(b, "verify_identity", { customer_id: cid, field: "date_of_birth", answer: id.date_of_birth }); return call(b, "verify_identity", { customer_id: cid, field: "phone_last4", answer: id.phone_last4 }); };

test("account refused until both questions pass, then returns products", async () => {
  const b = new Bank(spec, mem());
  assert.equal((await call(b, "get_account", { customer_id: cid })).json.error, "identity not verified");
  const r1 = await call(b, "verify_identity", { customer_id: cid, field: "date_of_birth", answer: id.date_of_birth });
  assert.deepEqual(r1.json, { ok: true, verified: true, wrong_answers_left: 3, all_verified: false });
  assert.equal((await verified(b)).json.all_verified, true);
  const a = (await call(b, "get_account", { customer_id: cid })).json;
  assert.equal(a.ok, true); assert.equal(a.products[0].product_id, "p1"); assert.equal(a.products[0].card_last4, spec.customers[0].products[0].card_last4);
});

test("three wrong answers in total end the check; unreadable date is not counted; swapped date gives hint", async () => {
  const b = new Bank(spec, mem());
  assert.equal((await call(b, "verify_identity", { customer_id: cid, field: "date_of_birth", answer: "March fourteenth" })).json.ok, false);
  const sw = (await call(b, "verify_identity", { customer_id: cid, field: "date_of_birth", answer: "1988-14-03" })); // invalid month -> unreadable, not counted
  assert.equal(sw.json.ok, false);
  const hint = (await call(b, "verify_identity", { customer_id: cid, field: "date_of_birth", answer: "1988-03-14".replace("03-14", "12-03") }));
  assert.equal(hint.json.wrong_answers_left, 2);
  const h2 = await call(b, "verify_identity", { customer_id: cid, field: "phone_last4", answer: "0000" });
  assert.equal(h2.json.wrong_answers_left, 1);
  const h3 = await call(b, "verify_identity", { customer_id: cid, field: "phone_last4", answer: "1111" });
  assert.equal(h3.json.wrong_answers_left, 0);
  assert.equal((await call(b, "verify_identity", { customer_id: cid, field: "phone_last4", answer: id.phone_last4 })).json.error, "too many wrong answers");
});

test("day/month swap hint", async () => {
  const s = structuredClone(spec); s.customers[0].identity.date_of_birth = "1988-03-12";
  const b = new Bank(s, mem());
  const r = await call(b, "verify_identity", { customer_id: cid, field: "date_of_birth", answer: "1988-12-03" });
  assert.equal(r.json.verified, false); assert.equal(r.json.hint, "day_month_swapped");
});

test("promise, one per product, note, callback, transfer, close; nothing after close; ledger shape", async () => {
  const b = new Bank(spec, mem());
  await verified(b);
  const p = await call(b, "create_promise", { customer_id: cid, product_id: "p1", amount: 126, date: "2026-10-20" });
  assert.equal(p.json.ok, true); assert.match(p.json.promise_id, /^pr_/);
  assert.equal((await call(b, "create_promise", { customer_id: cid, product_id: "p1", amount: 100, date: "2026-10-21" })).json.ok, false);
  assert.equal((await call(b, "create_promise", { customer_id: cid, product_id: "p9", amount: 100, date: "2026-10-21" })).json.error, "unknown product");
  assert.equal((await call(b, "add_note", { customer_id: cid, product_id: "p1", reason: "bogus" })).json.ok, false);
  assert.equal((await call(b, "add_note", { customer_id: cid, product_id: "p1", reason: "hardship", text: "lost job" })).json.ok, true);
  assert.equal((await call(b, "schedule_callback", { customer_id: cid, date: "2026-10-21", time: "25:00" })).json.ok, false);
  assert.equal((await call(b, "schedule_callback", { customer_id: cid, date: "2026-10-21", time: "10:30" })).json.ok, true);
  assert.equal((await call(b, "transfer_to_agent", { customer_id: cid, queue: "general" })).json.ok, true);
  assert.equal((await call(b, "close_call", { customer_id: cid, outcome: "promise" })).json.ok, true);
  assert.equal((await call(b, "get_account", { customer_id: cid })).json.error, "call already closed");
  const l = await b.scorerLedger(cid);
  assert.equal(l.outcome, "promise"); assert.equal(l.promises.length, 1); assert.equal(l.notes[0].reason, "hardship");
  assert.deepEqual(l.callbacks, [{ date: "2026-10-21", time: "10:30" }]); assert.equal(l.transfers[0].queue, "general");
  assert.equal(l.calls.at(-1).tool, "close_call");
});

test("unknown customer, state persists across Bank instances on the same store", async () => {
  const st = mem();
  assert.equal((await call(new Bank(spec, st), "get_account", { customer_id: "nope" })).json.error, "unknown customer");
  await verified(new Bank(spec, st));
  assert.equal((await call(new Bank(spec, st), "get_account", { customer_id: cid })).json.ok, true);
  assert.ok((await new Bank(spec, st).ledger()).length >= 4);
});

test("faults: 500 is not recorded in the call list and is consumed after `times`", async () => {
  const s = { ...spec, faults: [{ op: "schedule_callback", customer_id: null, times: 1 }] };
  const b = new Bank(s, mem());
  const a = await call(b, "schedule_callback", { customer_id: cid, date: "2026-10-21", time: "10:30" });
  assert.equal(a.status, 500);
  assert.equal((await call(b, "schedule_callback", { customer_id: cid, date: "2026-10-21", time: "10:30" })).status, 200);
  assert.equal((await b.scorerLedger(cid)).callbacks.length, 1);
  assert.equal((await call(b, "get_account", { customer_id: cid }, { "x-mock-fail": "1" })).status, 500);
});

test("missing spec parts degrade: no identity/products/rules blocks; param aliases; generic record + dispute", async () => {
  const mini = { tenant: "t", base_path: "", customers: [{ customer_id: "x", products: [{ type: "a" }] }],
    endpoints: [{ op: "dispute", path: "/d", method: "POST", params: { text: "details" }, request: { type: "object", properties: { customer_id: { type: "string" }, details: { type: "string" } }, required: ["customer_id", "details"] } },
      { op: "record", path: "/r", kind: "visit", request: { type: "object", properties: { customer_id: { type: "string" } }, required: ["customer_id"] } },
      { op: "get_account", path: "/a" }] };
  const b = new Bank(mini, mem());
  assert.equal((await b.call("POST", "/d", { customer_id: "x", details: "wrong fee" })).json.ok, true);
  assert.equal((await b.call("POST", "/d", { customer_id: "x" })).json.ok, false);
  assert.equal((await b.call("POST", "/r", { customer_id: "x", extra: 1 })).json.ok, true);
  const l = await b.scorerLedger("x");
  assert.equal(l.disputes[0].text, "wrong fee"); assert.equal(l.records.visit.length, 1);
  assert.equal((await b.call("POST", "/a", { customer_id: "x" })).json.ok, true);   // no identity block: no gate
  assert.equal(b.endpoint("POST", "/zzz"), undefined);
});

test("openapi is generated from the spec", () => {
  const o = openapi(spec, "https://w.example");
  assert.equal(o.servers[0].url, "https://w.example/brief-a/v1");
  assert.deepEqual(Object.keys(o.paths).sort(), spec.endpoints.map((e) => e.path).sort());
  assert.ok(o.paths["/verify_identity"].post.requestBody.content["application/json"].schema.required.includes("answer"));
});
