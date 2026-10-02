"""M16 evaluation: run the synthetic evaluation set through the real model and score it.

    docker compose run --rm api python -m scripts.run_ai_eval             # all 40 at once
    docker compose run --rm api python -m scripts.run_ai_eval --sample    # 12 items, one per label (M16 check)
    docker compose run --rm api python -m scripts.run_ai_eval --part 1    # items 1-20 (free tier: one part per day)
    docker compose run --rm api python -m scripts.run_ai_eval --part 2    # items 21-40, then the combined score

Each part saves its per-item results in ai_eval/results/ (inside the container: mount or copy to keep them);
once both parts exist, the combined score over all 40 decides PASS/FAIL.

Sends only the made-up emails in ai_eval/eval_set.json (no real data). Pass criteria (M16):
label accuracy >= 90% and 0 stored fields without verified evidence. An unverified label counts as wrong.
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app import settings  # noqa: F401  (tests patch the key through this module)
from app.ai_analysis import THROTTLE_SECONDS, AIError, analyse_text, default_model, env_provider, key_for, norm

SET = Path(__file__).resolve().parent.parent / "ai_eval" / "eval_set.json"
RESULTS = Path(__file__).resolve().parent.parent / "ai_eval" / "results"
BUSY_WAITS = [30, 90]  # seconds before retrying a busy (503) answer


def main(argv=sys.argv[1:]) -> int:
    provider = env_provider()
    model = default_model(provider)
    if not key_for(provider):
        print("No AI key: set OPENROUTER_API_KEY or GEMINI_API_KEY in .env")
        return 2
    items = json.loads(SET.read_text(encoding="utf-8"))
    if "--sample" in argv:  # one item per label (12): fits one day's free quota; >=90% means >=11/12
        items = list({it["expected"]: it for it in reversed(items)}.values())[::-1]
    part = int(argv[argv.index("--part") + 1]) if "--part" in argv else None
    if part is not None:
        half = len(items) // 2
        items = items[:half] if part == 1 else items[half:]
    rows = []
    for n, it in enumerate(items):
        if n:
            time.sleep(THROTTLE_SECONDS)
        # Every attempt counts against the free tier's daily quota, so retry sparingly.
        for attempt, wait in enumerate(BUSY_WAITS + [None]):
            try:
                r = analyse_text(it["subject"], it["body"], it["received"])
                break
            except AIError as e:
                if "rate limited" in str(e):  # daily quota used up: stop, save nothing, try after the reset
                    print(f"#{it['id']}: {e}\nQuota used up; nothing was saved. Run this part again after the "
                          "quota resets (midnight Pacific time).")
                    return 3
                if wait is None:
                    r = {"status": "error", "label": None, "extracted": {}, "dropped": [], "error": str(e)}
                else:
                    time.sleep(wait)
        got = r["label"] if r["status"] == "ok" else f"<{r['status']}: {r.get('error', '')}>"
        text = norm(r.get("analysed_text", ""))
        rows.append({"id": it["id"], "expected": it["expected"], "got": got, "error": r["status"] == "error",
                     "dropped": len(r.get("dropped", [])),
                     "unproven_stored": sum(1 for items_ in r["extracted"].values() for x in items_
                                            if norm(x["evidence"]) not in text)})
        mark = "ok " if got == it["expected"] else "XX "
        print(f"{mark}#{it['id']:>2} expected {it['expected']:<21} got {got}")
    if part is not None:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / f"part{part}.json").write_text(json.dumps({"model": model, "rows": rows}, indent=1))
        other = RESULTS / f"part{3 - part}.json"
        if not other.exists():
            print(f"\npart {part} saved; run --part {3 - part} (next day on the free tier) for the full score")
            return score(rows, final=False)
        rows = rows + json.loads(other.read_text())["rows"]
        print(f"\ncombined with part {3 - part}:")
    return score(rows)


def score(rows: list[dict], final: bool = True) -> int:
    correct = sum(r["got"] == r["expected"] for r in rows)
    errors = sum(r["error"] for r in rows)
    dropped = sum(r["dropped"] for r in rows)
    unproven_stored = sum(r["unproven_stored"] for r in rows)
    confusion = Counter((r["expected"], r["got"]) for r in rows)
    accuracy = correct / len(rows)
    print("\nmistakes:", {f"{e} -> {g}": c for (e, g), c in confusion.items() if e != g} or "none")
    print(f"label accuracy: {correct}/{len(rows)} = {accuracy:.1%} | model errors: {errors} | "
          f"model items dropped as unproven: {dropped} | stored fields without evidence: {unproven_stored}")
    passed = accuracy >= 0.90 and unproven_stored == 0
    if not final:
        print("partial result only (M16 is decided on all 40 items)")
        return 0
    print("M16 EVAL:", "PASS" if passed else "FAIL", f"(model {default_model(env_provider())}, {len(rows)} items)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
