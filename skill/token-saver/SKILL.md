---
name: token-saver
description: Minimize input, context, tool-output, and response token usage while preserving correctness. Use for routine Codex work, especially when the user asks to save tokens, be concise, reduce context, inspect large repositories, process long logs, or avoid unnecessary tool calls.
---

# Token Saver

Complete the task with the smallest useful context and response.

1. Read only files and line ranges relevant to the request. Search filenames and symbols before opening large files.
2. Limit command and tool output. Prefer targeted queries, counts, summaries, and small excerpts over full dumps.
3. Reuse facts already established in the current thread. Do not repeat explanations, plans, or results unless needed.
4. Skip optional background research, broad exploration, and speculative alternatives unless they materially affect the answer.
5. Ask a question only when proceeding would create meaningful risk or divergence. Otherwise make a reasonable, stated assumption.
6. Keep progress updates to one or two short sentences and send them only when tools or long-running work require updates.
7. Make the final answer outcome-first and concise. Include changed-file links, verification results, blockers, and essential caveats only.
8. Never trade away correctness, safety, requested verification, or necessary evidence merely to save tokens.

For large inputs, first identify the smallest relevant subset. Summarize older or repetitive material instead of reproducing it. Stop investigating when enough evidence exists to complete the requested task safely.
