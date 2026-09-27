# Project rules

## PROJECT.md is the single source of truth

[PROJECT.md](PROJECT.md) defines everything that gets built in this project.

1. **Build only what PROJECT.md describes.** No feature, milestone, dependency, service, screen or behaviour is implemented unless PROJECT.md covers it.
2. **Anything new needs the owner's approval first.** If something outside PROJECT.md seems needed:
   1. Stop and ask the owner. Explain what it is, why it is needed and what it affects.
   2. Wait for an explicit yes. No approval means no implementation.
   3. After approval, update PROJECT.md first: add the item and a row in the change log (§9) with date, version bump and "Approved by: Owner".
   4. Only then implement it.
3. **Changes and removals follow the same process.** Changing or dropping anything already in PROJECT.md also requires approval and a PROJECT.md update before the code changes.
4. **Open questions (PROJECT.md §8) and known gaps (§7) are not guesses.** Ask the owner before building a milestone they block. Record the answer in PROJECT.md before implementing.
5. **The safety rule in PROJECT.md §2 can never be relaxed** by an implementation shortcut. Changing it needs the same explicit approval as any other change.
6. **Track progress in [MILESTONES.md](MILESTONES.md).** Tick a milestone and update the progress count only after its "Done when" criteria in PROJECT.md pass.
7. **Follow the build order** in PROJECT.md §5. Do not start work past a GATE until that gate's exit criteria pass.
