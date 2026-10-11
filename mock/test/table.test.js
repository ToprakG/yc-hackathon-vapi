import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { TableBank, matches, fill, tableOpenapi, isTable } from "../src/table.js";

const spec = JSON.parse(fs.readFileSync(new URL("./fixtures/table-dummy.json", import.meta.url)));
function mem() {
  const m = new Map();
  return { get: async (k) => (m.has(k) ? structuredClone(m.get(k)) : undefined), put: async (k, v) => void m.set(k, structuredClone(v)), delete: async (k) => void m.delete(k),
    list: async (p) => [...m.entries()].filter(([k]) => k.startsWith(p)).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => [k, structuredClone(v)]) };
}
const run = (b, method, path, body, query) => b.call(method, "/api" + path, body ?? {}, {}, query ?? {});

test("operators and templating", () => {
  assert.ok(matches(5, "5")); assert.ok(matches({ $in: [1, 2] }, "2")); assert.ok(!matches({ $in: [1] }, 3));
  assert.ok(matches({ $exists: false }, undefined)); assert.ok(matches({ $regex: "^a", $flags: "i" }, "Abc")); assert.ok(matches({ $ci: "x" }, "X")); assert.ok(!matches({ $bogus: 1 }, 1));
  assert.deepEqual(fill({ a: "{{x}}", b: "n={{x}}", c: "{{nope}}" }, { x: 3 }), { a: 3, b: "n=3", c: null });
});

test("path params, rule order, default, exact status and body", async () => {
  const b = new TableBank(spec, mem());
  const a = await run(b, "GET", "/accounts/A1");
  assert.deepEqual([a.status, a.json], [200, { id: "A1", balance: 120.5, currency: "EUR", due: "2026-11-05" }]);
  assert.equal((await run(b, "GET", "/accounts/A2")).json.balance, 0);
  assert.equal((await run(b, "GET", "/accounts/A2", {}, { currency: "TRY" })).status, 404);   // $exists:false rule skipped -> default
  const u = await run(b, "GET", "/accounts/ZZ"); assert.deepEqual([u.status, u.json], [404, { error: "unknown account", id: "ZZ" }]);
  assert.equal(await run(b, "GET", "/nothing"), null);
  assert.equal(await run(b, "DELETE", "/accounts/A1"), null);   // method must match
});

test("writes are recorded and change later answers; sequence responses; ledger by key", async () => {
  const b = new TableBank(spec, mem());
  assert.equal((await run(b, "GET", "/accounts/A1/due-day")).json.day, 1);
  assert.equal((await run(b, "POST", "/accounts/A1/due-date", { day: 7 })).status, 422);
  assert.equal((await run(b, "POST", "/accounts/A1/due-date", { day: 15 })).status, 200);
  assert.equal((await run(b, "GET", "/accounts/A1/due-day")).json.day, 15);
  assert.equal((await run(b, "POST", "/accounts/A1/mail", { email: "a@b.co" })).status, 202);
  assert.equal((await run(b, "GET", "/accounts/X1")).status, 503); assert.equal((await run(b, "GET", "/accounts/X1")).json.balance, 7);
  const l = await b.scorerLedger("A1");
  assert.deepEqual(l.writes.map((w) => [w.kind, w.data]), [["due_date_change", { id: "A1", day: 15 }], ["email_sent", { id: "A1", to: "a@b.co" }]]);
  assert.equal(l.calls[0].tool, "current_day"); assert.equal(l.state.day_A1, 15);
  assert.equal((await b.scorerLedger("X1")).writes.length, 0);
  await b.reset("A1"); assert.equal((await b.writes()).length, 0); assert.equal((await b.ledger({ customer_id: "A1" })).length, 0);
  await b.reset(); assert.equal((await b.ledger()).length, 0); assert.deepEqual(await b.state(), {});
});

test("fault header and missing optional parts degrade", async () => {
  const b = new TableBank(spec, mem());
  const f = await b.call("GET", "/api/accounts/A1", {}, { "x-mock-fail": "1" }, {});
  assert.equal(f.status, 500); assert.equal((await b.scorerLedger("A1")).calls.length, 0);   // faults are not listed as calls
  const mini = new TableBank({ mode: "table", id: "m", endpoints: [{ method: "GET", path: "/p" }] }, mem());   // no rules, no default, no ledger_key, no base_path
  assert.deepEqual(await mini.call("GET", "/p", {}, {}, {}), { status: 404, json: { error: "no matching rule" } });
  const fb = new TableBank({ mode: "table", id: "m", fallback: { status: 418, body: { t: 1 } }, endpoints: [{ method: "GET", path: "/p" }] }, mem());
  assert.equal((await fb.call("GET", "/p", {}, {}, {})).status, 418);
  assert.equal(isTable(spec), true); assert.equal(isTable({}), false);
  const o = tableOpenapi({ ...spec, tenant: "t" }, "https://w"); assert.equal(o.servers[0].url, "https://w/t/api"); assert.ok(o.paths["/accounts/{id}"].get);
  const o2 = tableOpenapi({ tenant: "t", base_path: "/v9", openapi: { openapi: "3.0.0", servers: [{ url: "https://x" }], paths: { "/q": {} } } }, "https://w"); assert.deepEqual([o2.servers[0].url, Object.keys(o2.paths)], ["https://w/t/v9", ["/q"]]);
});

test("endsWith/startsWith, header inputs as ledger key, delay (capped)", async () => {
  const sp = { mode: "table", id: "h", ledger_key: ["header.x-cust", "cust"], max_delay: 0.05, endpoints: [{ name: "e", method: "POST", path: "/e", rules: [
    { when: { card: { $startsWith: "5400", $endsWith: "1234" }, "header.x-cust": "C1" }, status: 200, body: { who: "{{header.x-cust}}" }, delay_seconds: 99 },
    { when: { card: { $endsWith: "9999" } }, status: 201, body: {} }] }] };
  const b = new TableBank(sp, mem());
  const t0 = Date.now();
  const r = await b.call("POST", "/e", { card: "5400**1234" }, { "X-Cust": "C1" }, {});
  assert.deepEqual([r.status, r.json], [200, { who: "C1" }]); assert.ok(Date.now() - t0 < 1000);   // 99 s capped to 0.05 s
  assert.equal((await b.call("POST", "/e", { card: "x9999" }, {}, {})).status, 201);
  assert.equal((await b.call("POST", "/e", { card: "5400**1234" }, {}, {})).status, 404);   // header missing -> no rule
  assert.equal((await b.scorerLedger("C1")).calls.length, 1);
});

test("alias condition keys and per-rule ledger key", async () => {
  const sp = { mode: "table", id: "a", endpoints: [{ name: "e", method: "POST", path: "/e", rules: [{ key: "K1", when: { "customerNo|customerNumber": "42" }, status: 200, body: { ok: true }, record: { kind: "w" } }] }] };
  const b = new TableBank(sp, mem());
  assert.equal((await b.call("POST", "/e", { customerNumber: "42" }, {}, {})).status, 200);
  assert.equal((await b.call("POST", "/e", { customerNo: 42 }, {}, {})).status, 200);
  assert.equal((await b.call("POST", "/e", { other: "42" }, {}, {})).status, 404);
  const l = await b.scorerLedger("K1"); assert.equal(l.calls.length, 2); assert.equal(l.writes.length, 2);
});
