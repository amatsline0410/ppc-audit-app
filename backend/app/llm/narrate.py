"""Turn structured flags into plain-English narration or a client email.

Pure prompt-building + a single provider.complete() call. Works with any
provider; returns the NullProvider notice if LLM is disabled.
"""
from __future__ import annotations
from collections import Counter
from .providers import get_provider

SYSTEM = ("You are an expert Amazon PPC analyst. Be concise, concrete, and "
          "client-friendly. Use the numbers given. No fluff.")


def _summarize(flags: list[dict], target_acos: float) -> str:
    by = Counter(f["flag"] for f in flags)
    wasted = sum(f["observed"] for f in flags if f["flag"] == "WASTED_SPEND" and f.get("observed"))
    lines = [f"Target ACoS: {target_acos:.0%}", f"Total flags: {len(flags)}"]
    for k, v in by.most_common():
        lines.append(f"- {k}: {v}")
    lines.append(f"Estimated wasted spend flagged: ${wasted:,.0f}")
    top = sorted([f for f in flags if f.get("observed")],
                 key=lambda x: x["observed"], reverse=True)[:8]
    lines.append("Top items:")
    for f in top:
        lines.append(f"  {f['flag']} | {f.get('label') or f['entity_id']} | observed={f['observed']}")
    return "\n".join(lines)


def narrate(flags: list[dict], target_acos: float, mode: str = "summary") -> dict:
    provider = get_provider()
    facts = _summarize(flags, target_acos)
    if mode == "email":
        ask = ("Write a short client email (<=180 words) summarizing the audit findings "
               "and the actions being taken. Warm, confident, plain English.")
    else:
        ask = ("Write a tight analyst summary: the single root cause, the 3 highest-impact "
               "actions, and the expected effect on ACoS. <=160 words.")
    prompt = f"{ask}\n\nAUDIT DATA:\n{facts}"
    text = provider.complete(prompt, system=SYSTEM)
    return {"provider": provider.name, "enabled": provider.available(), "text": text}
