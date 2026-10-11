// node test/table_check.mjs <mock_url> <spec.json>
// Runs spec.checks ([{name, request:{method,path,query?,body?}, expect:{status, body?(subset)}}]) against the live tenant, then spec.expect_writes
// (subset match on GET <mock_url>/writes). The tenant is reset by the caller. Exit 1 on any failure.
import fs from "node:fs";
const [url, specFile] = process.argv.slice(2);
const spec = JSON.parse(fs.readFileSync(specFile, "utf8"));
const base = (spec.base_path || "");
const subset = (want, got) => want !== null && typeof want === "object"
  ? got !== null && typeof got === "object" && Object.entries(want).every(([k, v]) => subset(v, got[k]))
  : String(want) === String(got);
let bad = 0;
const say = (ok, name, extra = "") => { if (!ok) bad++; { if (!ok || process.env.VERBOSE) console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra}`); }; };
const runCheck = async (c) => {
  const r = c.request, q = r.query ? "?" + new URLSearchParams(r.query) : "";
  const res = await fetch(url + base + r.path + q, { method: r.method || "GET", headers: { ...(r.body ? { "content-type": "application/json" } : {}), ...(r.headers || {}) }, body: r.body ? JSON.stringify(r.body) : undefined });
  const txt = await res.text(); let body; try { body = JSON.parse(txt); } catch { body = txt; }
  const ok = res.status === (c.expect.status ?? 200) && (c.expect.body === undefined || subset(c.expect.body, body));
  say(ok, c.name || r.path, ok ? "" : `: got ${res.status} ${txt.slice(0, 200)}`);
};
// checks run in order within a batch of 1 when the table has writes/state/sequences, else 8 at a time
const par = spec.checks_parallel ?? 1;
const list = spec.checks || [];
for (let i = 0; i < list.length; i += par) await Promise.all(list.slice(i, i + par).map(runCheck));
if (spec.expect_writes) {
  const w = (await (await fetch(url + "/writes")).json()).writes || [];
  for (const e of spec.expect_writes) say(w.some((x) => x.kind === e.kind && subset(e.data || {}, x.data)), `write ${e.kind}`, "");
}
console.log(bad ? `${bad} FAILED` : "all checks passed");
process.exit(bad ? 1 : 0);
