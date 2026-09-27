"""M16 evaluation: run the synthetic evaluation set through the real model and score it.

    docker compose run --rm api python -m scripts.run_ai_eval

Sends only the made-up emails in ai_eval/eval_set.json (no real data). Pass criteria (M16):
label accuracy >= 90% and 0 stored fields without verified evidence. An unverified label counts as wrong.
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app import settings
from app.ai_analysis import THROTTLE_SECONDS, AIError, analyse_text, norm

SET = Path(__file__).resolve().parent.parent / "ai_eval" / "eval_set.json"


def main() -> int:
    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set in .env")
        return 2
    items = json.loads(SET.read_text(encoding="utf-8"))
    correct, errors, unproven_stored, dropped = 0, 0, 0, 0
    confusion = Counter()
    for n, it in enumerate(items):
        if n:
            time.sleep(THROTTLE_SECONDS)
        for attempt in range(3):
            try:
                r = analyse_text(it["subject"], it["body"], it["received"])
                break
            except AIError as e:
                if attempt == 2:
                    r = {"status": "error", "label": None, "extracted": {}, "dropped": [], "error": str(e)}
                else:
                    time.sleep(20)
        got = r["label"] if r["status"] == "ok" else f"<{r['status']}>"
        errors += r["status"] == "error"
        correct += got == it["expected"]
        confusion[(it["expected"], got)] += 1
        dropped += len(r.get("dropped", []))
        text = norm(r.get("analysed_text", ""))
        unproven_stored += sum(1 for items_ in r["extracted"].values() for x in items_ if norm(x["evidence"]) not in text)
        mark = "ok " if got == it["expected"] else "XX "
        print(f"{mark}#{it['id']:>2} expected {it['expected']:<21} got {got}")
    accuracy = correct / len(items)
    print("\nmistakes:", {f"{e} -> {g}": c for (e, g), c in confusion.items() if e != g} or "none")
    print(f"label accuracy: {correct}/{len(items)} = {accuracy:.1%} | model errors: {errors} | "
          f"model items dropped as unproven: {dropped} | stored fields without evidence: {unproven_stored}")
    passed = accuracy >= 0.90 and unproven_stored == 0
    print("M16 EVAL:", "PASS" if passed else "FAIL", f"(model {settings.GEMINI_MODEL})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
