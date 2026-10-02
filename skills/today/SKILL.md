---
name: today
description: Write the plan for today (focus items in order, what to check first, which open sessions to resume) from the last daily report, recent Claude Code sessions and the open TODO items. Use when the user runs /today.
disable-model-invocation: true
---

Build the plan in a subagent, so the raw facts stay out of this conversation.

1. Call the Agent tool with `subagent_type: "general-purpose"`, `description: "Write today's plan"`, and the prompt below with DAY set to today's date (YYYY-MM-DD). Wait for the result.
2. Show the plan text from the result exactly as it is, then one line with the file path. Nothing else.

Prompt for the subagent:

> Write the plan for today, DAY.
> 1. Run `todo plan`. It prints the plan file path, the Tomorrow and Blockers parts of the last daily report, the Claude Code sessions of the last 4 days (with resume commands), and all open TODO items with IDs.
> 2. Write the plan. Short sentences, common words, active voice. Keep real names: PR/MR numbers, ticket IDs, TODO IDs (tN).
>    - Work only. Leave out personal sessions (games, home, general questions) unless a TODO item names them.
>    - Order the focus items: first what others wait for (reviews, merges, answers, deadlines), then Active items that the last report said to do next, then the rest.
>    - "Check first" lists blockers that may have moved since the last report: who to ask or what to look at.
>    - "Sessions to resume" lists at most 4 work sessions that match today's focus.
>    - Use the sources only. Do not invent deadlines or results.
>
>    Format:
>    ```
>    # Plan for DAY
>
>    ## Focus
>    1. <task> (tN) — <why now, one short sentence>     (3–5 items)
>
>    ## Check first
>    - <blocker> — <who to ask / what to look at>       (or "None")
>
>    ## Sessions to resume
>    - <title> — `<resume command>`    (or "None")
>    ```
> 3. Save it to the plan file path from step 1 (create the folder if needed). Overwrite an existing file for the same day.
> 4. Return the plan text and the file path. Nothing else.
