# Cross-model verification

This is the single highest-leverage habit in the SETUP.md discipline set. The model is trained to agree with you. After 15+ exchanges on a hard decision, it is no longer a peer; it is an echo chamber. The fix is mechanical.

## The rule

When **all three** of these are true, STOP before acting:

1. You have been in the current conversation for **15+ exchanges**.
2. The current decision is **hard** — architectural choice, identity-resolution algorithm, attribution model, metric semantics, agent eval design, storage shape, anything reversible only at high cost.
3. Claude is **agreeing with you** or has not strongly pushed back recently.

Paste the key context into a **second model** and ask the same question. The second model has no conversational momentum to honor.

## What "key context" means

- The decision being made, stated in one paragraph.
- The two or three concrete options.
- The current leading answer and its rationale.
- The user's constraints and non-negotiables.

Do **not** paste the full conversation. The whole point is to break the conversational frame; bringing it with you defeats the exercise.

## Second-model options

The user should pick one and stick with it for consistency:

- **Gemini 2.5 Pro** — different RLHF lineage; tends to disagree more freely on architectural calls.
- **GPT-5** — different training data; useful for "is there a standard answer I'm missing".
- **DeepSeek / Qwen / Kimi K2** — open-weight models for cases where the user wants a less RLHF'd take.
- **A second Claude session with the explicit prompt "be adversarial"** — weakest option; still subject to family-level bias. Use only when nothing else is available.

> **TODO** — user, pick your default second model and record it here.

## What to do with the second model's answer

- **Disagrees.** Treat as a high-signal flag. Go back to the original conversation with the disagreement quoted verbatim and a request to address it directly.
- **Agrees.** You have verification. Proceed, but write a `[VERIFICATION]` line in `tasks/lessons.md` so you remember which decisions were second-model-checked.
- **Punts** (says "depends on..."). The decision is genuinely under-specified. Resolve the underspecification before continuing.

## Anti-patterns

- **Skipping this when you "feel sure".** Feeling sure after 15 exchanges with an agreeable model is exactly the failure mode this defends against.
- **Pasting the entire conversation.** Brings the bias with you. Distill to one paragraph + options + leading answer.
- **Treating the second model as an oracle.** It is a second opinion, not a tiebreaker. Disagreement is a signal to think harder, not to flip.
- **Using the same model family for verification.** A second Claude session inherits most of the bias. Use a different lineage when possible.
