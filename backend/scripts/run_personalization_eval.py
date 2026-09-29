"""M9 / Phase 2 exit: no ungrounded AI claim may reach a draft.

    docker compose run --rm api python -m scripts.run_personalization_eval          # grounding check vs labelled set
    docker compose run --rm api python -m scripts.run_personalization_eval --real   # + real model output to review

The labelled set (ai_eval/personalization_set.json) holds hand-labelled candidate sentences, including hostile ones
(invented numbers, names, funding, wrong citations). PASS = zero ungrounded sentences accepted. Sentences that are
grounded but rejected are reported (they only cost personalization, never safety).
"""
import json
import sys
from pathlib import Path

from app import settings
from app.ai_analysis import AIError
from app.personalize import ask_model, ground

SET = Path(__file__).resolve().parent.parent / "ai_eval" / "personalization_set.json"


def main(argv=sys.argv[1:]) -> int:
    cases = json.loads(SET.read_text(encoding="utf-8"))
    false_accepts, false_rejects, total = [], [], 0
    for case in cases:
        for c in case["candidates"]:
            total += 1
            kept, dropped = ground({"sentences": [{"text": c["text"], "fact_ids": c["fact_ids"]}]}, case["facts"], case["company"])
            accepted = bool(kept)
            if accepted and not c["grounded"]:
                false_accepts.append(f"{case['company']}: {c['text']}")
            if c["grounded"] and not accepted:
                false_rejects.append(f"{case['company']}: {c['text']} ({dropped[0]['reason']})")
    print(f"candidates: {total} | ungrounded accepted: {len(false_accepts)} | grounded rejected: {len(false_rejects)}")
    for x in false_accepts:
        print("  UNGROUNDED ACCEPTED:", x)
    for x in false_rejects:
        print("  grounded but rejected:", x)

    if "--real" in argv:
        if not settings.GEMINI_API_KEY:
            print("GEMINI_API_KEY is not set in .env")
            return 2
        for case in cases[:5]:  # 5 requests: stays inside the free tier
            try:
                kept, dropped = ground(ask_model(case["company"], case["facts"], "Machine Learning Engineer",
                                                 settings.GEMINI_MODEL), case["facts"], case["company"])
            except AIError as e:
                print(f"\n{case['company']}: model error: {e}")
                if "rate limited" in str(e):
                    break
                continue
            print(f"\n{case['company']}:")
            for s in kept:
                print("  KEPT   ", s["text"], "| cites", [f["id"] for f in s["facts"]])
            for s in dropped:
                print("  DROPPED", s["text"], "|", s["reason"])
    passed = not false_accepts
    print("\nM9 GROUNDING EVAL:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
