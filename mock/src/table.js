// Table mode: a JSON table of endpoints -> rules (match on path params / query / body fields) -> canned {status, body}, plus recorded writes.
// Same store interface as engine.js.Bank. Spec shape is documented in SPEC.md ("Table mode").
const pad = (n) => String(n).padStart(8, "0");

export const isTable = (s) => s && s.mode === "table";

// "/cards/{n}/statement" -> {re, names}
function compilePath(p) {
  const names = [];
  const re = new RegExp("^" + p.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{(\w+)\}/g, (_, n) => (names.push(n), "([^/]+)")) + "/?$");
  return { re, names };
}
const get = (o, path) => path.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
// a condition key "a|b|c" reads the first of those input names that is present (field names the document leaves open)
const pick = (ctx, k) => { for (const n of k.split("|")) { const v = get(ctx, n); if (v !== undefined && v !== null) return v; } return undefined; };
const loose = (a, b) => a === b || (a != null && b != null && typeof a !== "object" && typeof b !== "object" && String(a) === String(b));

export function matches(cond, v) {
  if (cond !== null && typeof cond === "object" && !Array.isArray(cond)) {
    for (const [op, arg] of Object.entries(cond)) {
      if (op === "$in") { if (!arg.some((x) => loose(x, v))) return false; }
      else if (op === "$ne") { if (loose(arg, v)) return false; }
      else if (op === "$exists") { if ((v !== undefined && v !== null) !== !!arg) return false; }
      else if (op === "$regex") { if (v == null || !new RegExp(arg, cond.$flags || "").test(String(v))) return false; }
      else if (op === "$endsWith") { if (v == null || !String(v).endsWith(String(arg))) return false; }
      else if (op === "$startsWith") { if (v == null || !String(v).startsWith(String(arg))) return false; }
      else if (op === "$ci") { if (v == null || String(v).toLowerCase() !== String(arg).toLowerCase()) return false; }
      else if (op === "$gt") { if (!(Number(v) > Number(arg))) return false; }
      else if (op === "$lt") { if (!(Number(v) < Number(arg))) return false; }
      else if (op === "$flags") continue;
      else return false;   // unknown operator never matches
    }
    return true;
  }
  return loose(cond, v);
}

// "{{name}}" as the whole string keeps the value's type; embedded -> string. Unknown names become null / empty.
export function fill(tpl, ctx) {
  if (typeof tpl === "string") {
    const whole = tpl.match(/^\{\{\s*([\w.$-]+)\s*\}\}$/);
    if (whole) return get(ctx, whole[1]) ?? null;
    return tpl.replace(/\{\{\s*([\w.$-]+)\s*\}\}/g, (_, n) => String(get(ctx, n) ?? ""));
  }
  if (Array.isArray(tpl)) return tpl.map((x) => fill(x, ctx));
  if (tpl && typeof tpl === "object") return Object.fromEntries(Object.entries(tpl).map(([k, v]) => [k, fill(v, ctx)]));
  return tpl;
}

export class TableBank {
  constructor(spec, store, now = () => new Date()) {
    this.spec = spec; this.store = store; this.now = now;
    this.eps = (spec.endpoints || []).map((e, i) => ({ ...e, _i: i, _p: compilePath(e.path) }));
  }
  base() { return this.spec.base_path || ""; }

  find(method, path) {
    const b = this.base();
    if (b && !path.startsWith(b)) return null;
    const rest = path.slice(b.length) || "/";
    for (const e of this.eps) {
      if ((e.method || "GET").toUpperCase() !== method) continue;
      const m = rest.match(e._p.re);
      if (m) return { ep: e, params: Object.fromEntries(e._p.names.map((n, i) => [n, decodeURIComponent(m[i + 1])])) };
    }
    return null;
  }

  async log(entry) {
    const seq = ((await this.store.get("seq")) || 0) + 1;
    await this.store.put("seq", seq);
    const e = { seq, ts: this.now().toISOString(), ...entry };
    await this.store.put("L:" + pad(seq), e);
    return e;
  }
  async state() { return (await this.store.get("S")) || {}; }

  // Returns {status, json} or null when no endpoint matches the path (the Worker answers 404).
  async call(method, path, body = {}, headers = {}, query = {}) {
    const hit = this.find(method, path);
    if (!hit) return null;
    const { ep, params } = hit;
    const inputs = { ...query, ...(body && typeof body === "object" && !Array.isArray(body) ? body : {}), ...params };
    const name = ep.name || `${method} ${ep.path}`;
    const state = await this.state();
    const header = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
    const ctx = { ...inputs, in: inputs, path: params, query, body, header, state, now: this.now().toISOString() };

    if (headers["x-mock-fail"] === "1") {
      const r = { status: 500, body: { error: "service error" } };
      await this.log({ tool: name, key: this.key(ctx), args: inputs, result: r, fault: true });
      return { status: 500, json: r.body };
    }
    let rule = null, ri = -1;
    for (const [i, r] of (ep.rules || []).entries()) {
      const when = r.when || {};
      if (Object.entries(when).every(([k, c]) => matches(c, pick(ctx, k)))) { rule = r; ri = i; break; }
    }
    let out = rule ?? ep.default ?? this.spec.fallback ?? { status: 404, body: { error: "no matching rule" } };
    if (rule?.sequence?.length) {
      const nk = `N:${ep._i}:${ri}`, n = (await this.store.get(nk)) || 0;
      await this.store.put(nk, n + 1);
      out = rule.sequence[Math.min(n, rule.sequence.length - 1)];
    }
    const status = out.status ?? 200, resp = fill(out.body ?? {}, ctx);
    const delay = Math.min(Number(out.delay ?? rule?.delay ?? 0) || 0, this.spec.max_delay ?? 25);   // seconds; a slow service
    if (delay > 0) await new Promise((r) => setTimeout(r, delay * 1000));
    const recs = [];
    for (const rec of [].concat(rule?.record ?? [], out !== rule ? out.record ?? [] : [])) {
      const r = { kind: fill(rec.kind, ctx), data: fill(rec.data ?? inputs, ctx), key: rule?.key ?? this.key(ctx) };
      recs.push(r); await this.store.put("W:" + pad(((await this.store.get("seq")) || 0) + 1) + ":" + recs.length, { ...r, ts: this.now().toISOString() });
    }
    const set = { ...(rule?.set ?? {}), ...(out.set ?? {}) };
    if (Object.keys(set).length) await this.store.put("S", { ...state, ...fill(set, ctx) });
    await this.log({ tool: name, key: rule?.key ?? this.key(ctx), args: inputs, result: { status, body: resp }, matched: rule ? ri : null, writes: recs.length || undefined });
    return { status, json: resp };
  }

  key(ctx) {   // ledger_key entries are input names, or "header.<name>" (lower case)
    for (const k of [].concat(this.spec.ledger_key ?? [])) { const v = get(ctx, k); if (v != null && v !== "") return String(v); }
    return null;
  }
  async ledger({ customer_id, limit } = {}) {
    let rows = (await this.store.list("L:")).map(([, v]) => v);
    if (customer_id) rows = rows.filter((r) => r.key === customer_id || Object.values(r.args || {}).some((v) => loose(v, customer_id)));
    return limit ? rows.slice(-limit) : rows;
  }
  async writes(key) {
    return (await this.store.list("W:")).map(([, v]) => v).filter((w) => !key || w.key === key);
  }
  async scorerLedger(key) {
    const calls = (await this.ledger({ customer_id: key })).filter((r) => !r.fault).map(({ seq, ts, tool, args, result }) => ({ seq, ts, tool, args, result }));
    return { key, writes: await this.writes(key), calls, state: await this.state() };
  }
  async publicState() { return { state: await this.state(), writes: await this.writes(), calls: (await this.store.list("L:")).length }; }
  async reset(key) {
    for (const [k, v] of await this.store.list("L:")) if (!key || v.key === key) await this.store.delete(k);
    for (const [k, v] of await this.store.list("W:")) if (!key || v.key === key) await this.store.delete(k);
    if (!key) for (const p of ["N:", "S"]) for (const [k] of await this.store.list(p)) await this.store.delete(k);
  }
}

export function tableOpenapi(spec, origin) {
  const server = { url: `${origin}/${spec.tenant}${spec.base_path || ""}` };
  if (spec.openapi) return { ...spec.openapi, servers: [server] };   // the bank's own document, only the server is ours
  const paths = {};
  for (const e of spec.endpoints || []) (paths[e.path] ||= {})[(e.method || "GET").toLowerCase()] = { summary: e.summary || e.name || e.path, responses: { 200: { description: "ok" } } };
  return { openapi: "3.0.3", info: spec.info || { title: spec.tenant, version: "1.0" }, servers: [server], paths };
}
