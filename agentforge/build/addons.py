"""Prompt add-ons for TEST_PLAN section 2: the P1 behaviour bundle and the one-at-a-time variants.

An add-on is a block of rules appended to a built agent's system prompt, rendered with the brief's own tool names and
limits. Variants made this way differ from their parent only by that block, so a paired comparison measures the block.
Add-ons that win are written to LOCKED_PATH and the collections builder appends them to every new build.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agentforge.config import RESULTS_DIR
from agentforge.domain.collections.policy import CANONICAL_TOOLS, Policy
from agentforge.schemas import AgentConfig

LOCKED_PATH = RESULTS_DIR / "collections" / "locked_addons.json"


@dataclass(frozen=True)
class Addon:
    key: str
    text: Callable[[Policy], str]
    checks: tuple[str, ...] = ()  # decision checks this item is meant to fix; used to pick P1 items from failures
    test: str = "P1"  # TEST_PLAN id this add-on belongs to
    # Why this add-on must not be added for a brief (it would contradict or merely restate it), or None.
    skip: Callable[[Policy], str | None] = lambda p: None


def _t(p: Policy, name: str) -> str:
    return p.tool(name)


def _limits_sentence(p: Policy) -> str:
    if not p.allow_plans:
        return (f"Limitler: taksit yok; yalnızca gecikmiş tutarın tamamı, en geç {p.max_promise_days} gün içinde ödenebilir.")
    text = (f"Limitler: en fazla {p.max_installments} taksit; ilk ödeme gecikmiş tutarın en az %{p.min_first_payment_pct:g}'i "
            f"ve en geç {p.max_promise_days} gün içinde")
    if p.min_installment_tl:
        text += f"; her taksit en az {p.min_installment_tl:g} TL"
    if p.allow_discount:
        text += f"; indirim en fazla %{p.max_discount_pct:g}, yalnızca {_discount_condition(p)}"
    return text + "."


def _discount_condition(p: Policy) -> str:
    days = f" ve en geç {p.discount_max_days} gün içinde" if p.discount_max_days is not None else ""
    return f"tamamı tek seferde{days} ödenirse"


def _limits_table(p: Policy) -> str:
    rows = [("Taksit", f"en fazla {p.max_installments}" if p.allow_plans else "yok"),
            ("İlk ödeme", f"gecikmiş tutarın en az %{p.min_first_payment_pct:g}'i" if p.allow_plans else "tutarın tamamı"),
            ("Ödeme tarihi", f"bugünden itibaren en geç {p.max_promise_days} gün")]
    if p.min_installment_tl:
        rows.append(("Taksit tutarı", f"en az {p.min_installment_tl:g} TL"))
    rows.append(("İndirim", f"en fazla %{p.max_discount_pct:g}, yalnızca {_discount_condition(p)}" if p.allow_discount else "yok"))
    return "Limitler:\n| Konu | Kural |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows)


def _examples(p: Policy) -> str:
    """Example calls that every brief allows: a full one-off payment (valid even without plans) and the brief's own
    third-party message."""
    promise = _t(p, "log_promise_to_pay")
    return (
        "Örnek diyaloglar (üslup ve sıra için; tutarları ve isimleri her çağrıda araçtan al):\n"
        f"Müşteri: Ay sonu gibi bir şeyler yatırırım.\nSen: Anlıyorum. Hangi gün ve ne kadar ödeyebileceğinizi söylerseniz "
        f"kaydedeyim.\nMüşteri: Yarın tamamını yatırırım.\nSen: Yarın gecikmiş tutarın tamamını tek seferde ödeyeceksiniz, "
        f"doğru mu?\nMüşteri: Evet.\nSen: ({promise} çağır) Kaydettim, teşekkür ederim.\n"
        # Briefs phrase this as a script or as an instruction, so it is shown as the rule, not as words to say.
        f"Arayan (eş): Ne için aradınız, borç mu var?\nSen: [üçüncü kişi kuralı: {p.third_party_message}] Başka bilgi vermem."
    )


def _route_and_end(p: Policy) -> str:
    if p.hardship_action == "plan":  # e.g. anadolu_tr: hardship gets a small plan, not an ended call
        return ("Müşteri borca itiraz ederse veya aranmak istemezse ısrar etme ve tahsilata devam etme: itiraz için "
                f"{_t(p, 'log_dispute')}, aranmasın için {_t(p, 'mark_do_not_call')} çağır ve görüşmeyi nazikçe bitir. "
                "Maddi zorlukta baskı yapma; brief'in izin verdiği küçük ilk ödemeli planı ara.")
    route = {"transfer": _t(p, "transfer_to_human"), "callback": _t(p, "schedule_callback")}.get(p.hardship_action, "brief'teki yol")
    return ("Müşteri maddi zorluk anlatırsa, borca itiraz ederse veya aranmak istemezse ısrar etme ve tahsilata devam etme: "
            f"ilgili aracı çağır (zorluk için {route}, itiraz için {_t(p, 'log_dispute')}, aranmasın için "
            f"{_t(p, 'mark_do_not_call')}) ve görüşmeyi nazikçe bitir.")


def _no_fake_confirmation(p: Policy) -> str:
    fallback = ("izin verilen en yakın seçeneği öner ve tekrar onay al" if p.allow_plans else
                "yalnızca tutarın tamamını öner; müşteri ödeyemiyorsa daha küçük tutar pazarlığı yapma, brief'teki yola git")
    return f"Bir araç hata dönerse işlem yapılmış gibi konuşma. Hatayı sade dille söyle; limit hatasında {fallback}."


def _order_decided(p: Policy) -> str | None:
    if not p.allow_plans:
        return "no payment plans in this brief, so there is no order to choose"
    if p.payment_order != "unspecified":
        return f"the brief fixes the order ({p.payment_order})"
    return None


ADDONS: dict[str, Addon] = {a.key: a for a in [
    # --- P1 bundle (TEST_PLAN section 2) ---
    Addon("say_and_log", lambda p: "Yaptığın her işlemi müşteriye yüksek sesle söyle ve görüşme bitmeden ilgili aracı çağırarak "
                                   "kaydet; söylediğin ama kaydetmediğin işlem yapılmamış sayılır.",
          ("required_tools_called",)),
    Addon("closing_checklist", lambda p: "Görüşmeyi kapatmadan önce kontrol et: sonuç (ödeme sözü, itiraz, geri arama, aranmasın "
                                         f"veya aktarma) ilgili araçla kaydedildi mi? ({_t(p, 'log_promise_to_pay')}, "
                                         f"{_t(p, 'log_dispute')}, {_t(p, 'schedule_callback')}, {_t(p, 'mark_do_not_call')}, "
                                         f"{_t(p, 'transfer_to_human')}). Sonra sonucu tek cümleyle özetle.",
          ("required_tools_called",)),
    Addon("confirm_then_call", lambda p: "Müşteri ödeme sözü verdiğinde tutarı, tarihi ve varsa taksit sayısını aynen tekrar et, açık bir 'evet' al ve "
                                         f"hemen {_t(p, 'log_promise_to_pay')} çağır. Tarih ve tutar belirsizse ('bakarım', "
                                         "'ay sonu gibi') bu bir söz değildir; net gün ve tutar sor, alamazsan kaydetme.",
          ("promise_confirmed_before_logging", "specific_date_and_amount_asked", "forbidden_tools_not_called")),
    Addon("route_and_end", _route_and_end,
          ("no_pressure_after_dispute", "no_promise_after_dispute", "required_tools_called")),
    Addon("short_turns", lambda p: "Her konuşma turun en fazla bir iki kısa cümle olsun ve tek soru sor. Liste, madde işareti veya "
                                   "uzun açıklama yapma." + (" Brief'in kelimesi kelimesine istediği metinler bu kuralın dışındadır."
                                                             if p.strict else ""),
          ("stayed_professional",)),
    Addon("rules_at_moment", lambda p: "Kuralları ilgili anda uygula: doğrulamadan önce borçtan, tutardan ve üründen hiç bahsetme; "
                                       f"söz alırken limitleri kontrol et; {_t(p, 'log_promise_to_pay')} çağırmadan önce onay al; "
                                       "kapanışta sonucu özetle.",
          ("debt_mentioned_before_verification", "promises_within_limits")),
    Addon("no_fake_confirmation", _no_fake_confirmation,
          ("promises_within_limits", "limit_stated")),
    Addon("keep_verification", lambda p: "Doğrulama durumu görüşme boyunca geçerlidir: konu değişse de doğrulanmamış kişiye hesap "
                                         "bilgisi verme, doğrulanmış müşteriden aynı bilgileri tekrar isteme.",
          ("account_read_after_verification", "amount_not_spoken_before_verification", "debt_mentioned_before_verification")),
    # --- one-at-a-time tests after the bundle ---
    Addon("full_payment_first", lambda p: "Önce gecikmiş tutarın tamamını teklif et; müşteri ödeyemeyeceğini söylerse taksit seçeneğine geç.",
          test="T2.2", skip=_order_decided),
    Addon("plan_first", lambda p: "Müşteriye tutarı söyledikten sonra doğrudan limitler içindeki taksit seçeneğini öner; tamamını "
                                  "ödemek isterse onu kaydet.",
          test="T2.2", skip=_order_decided),
    Addon("limits_table", _limits_table, test="T2.3"),
    Addon("limits_sentence", _limits_sentence, test="T2.3"),
    Addon("examples", _examples, test="T2.4"),
]}

P1 = [k for k, a in ADDONS.items() if a.test == "P1"]
SINGLE_TESTS = {"T2.2": ("full_payment_first", "plan_first"), "T2.3": ("limits_table", "limits_sentence"), "T2.4": ("examples", None)}


def render_rule(rule: str, policy: Policy) -> str:
    """Free-text rules (GEPA, lessons library) name tools as {log_promise_to_pay}; filled with the brief's own names."""
    for name in CANONICAL_TOOLS:
        rule = rule.replace("{" + name + "}", policy.tool(name))
    return rule


def applicable(policy: Policy, keys: list[str]) -> list[str]:
    return [k for k in keys if ADDONS[k].skip(policy) is None]


def render(policy: Policy, keys: list[str], rules: list[str] | None = None) -> str:
    lines = [ADDONS[k].text(policy) for k in applicable(policy, keys)] + [render_rule(r, policy) for r in rules or []]
    if not lines:
        return ""
    return "## Ek kurallar\n" + "\n".join(f"- {line}" if "\n" not in line else line for line in lines)


def apply_addons(cfg: AgentConfig, policy: Policy, keys: list[str], label: str | None = None,
                 rules: list[str] | None = None) -> AgentConfig:
    block = render(policy, keys, rules)
    if not block and not label:
        return cfg
    tag = "+".join(keys) if keys and len(keys) <= 2 and not rules else f"{len(keys) + len(rules or [])}addons"
    return cfg.model_copy(update={
        "version_label": label or f"{cfg.version_label}+{tag}",
        # Add-ons that would contradict the brief are skipped; with nothing left the prompt is the parent's.
        "system_prompt": f"{cfg.system_prompt}\n\n{block}" if block else cfg.system_prompt,
        "parent_version": cfg.version_label,
        "notes": f"add-ons: {', '.join(keys)}" + (f"; {len(rules)} rules" if rules else ""),
    })


def growth(cfg: AgentConfig, policy: Policy, key: str) -> float:
    """How much one add-on lengthens the prompt, as a fraction (the plan singles out items above 0.30)."""
    if ADDONS[key].skip(policy) is not None:
        return 0.0
    return len(ADDONS[key].text(policy)) / max(1, len(cfg.system_prompt))


def load_locked(path: Path | None = None) -> list[str]:
    return _read(path)["addons"]


def load_locked_rules(path: Path | None = None) -> list[str]:
    """Template rules merged from GEPA-lite and the lessons library (section 4)."""
    return _read(path)["rules"]


def lock_rules(rules: list[str], reason: str, path: Path | None = None) -> list[str]:
    path = path or LOCKED_PATH
    current = _read(path)
    current["rules"] = list(dict.fromkeys([*current["rules"], *rules]))
    current["log"].append({"rules": rules, "reason": reason})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n")
    return current["rules"]


def _read(path: Path | None) -> dict:
    path = path or LOCKED_PATH
    data = json.loads(path.read_text()) if path.exists() else {}
    return {"addons": [], "rules": [], "builder": {}, "workflow": None, "log": [], **data}


def load_builder_options(path: Path | None = None) -> dict:
    """Locked builder flags from T2.5/T2.6, e.g. {"prompt_language": "en", "reading": "conservative"}."""
    return _read(path)["builder"]


def lock_builder_option(key: str, value: str, reason: str, path: Path | None = None) -> dict:
    path = path or LOCKED_PATH
    current = _read(path)
    current["builder"][key] = value
    current["log"].append({"builder": {key: value}, "reason": reason})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n")
    return current["builder"]


def load_locked_workflow(path: Path | None = None) -> dict | None:
    return _read(path)["workflow"]


def lock_workflow(graph: dict, reason: str, path: Path | None = None) -> None:
    """AFlow-lite winner: the collections builder attaches this graph to every build."""
    path = path or LOCKED_PATH
    current = _read(path)
    current["workflow"] = graph
    current["log"].append({"workflow": graph.get("name"), "reason": reason})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n")


def lock(keys: list[str], reason: str, path: Path | None = None) -> list[str]:
    path = path or LOCKED_PATH
    current = _read(path)
    current["addons"] = [k for k in [*current["addons"], *keys] if k in ADDONS]
    current["addons"] = list(dict.fromkeys(current["addons"]))
    current["log"].append({"added": keys, "reason": reason})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n")
    return current["addons"]
