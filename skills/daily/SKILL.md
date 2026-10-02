---
name: daily
description: Write a daily standup report (what I worked on, plan for tomorrow, blockers) from the day's Claude Code sessions, git commits and the TODO list. Use when the user runs /daily.
disable-model-invocation: true
argument-hint: "[YYYY-MM-DD | yesterday]"
---

Build the daily report in a subagent, so the raw facts stay out of this conversation.

1. Work out the day: `$ARGUMENTS` is a date, or `yesterday`, or empty (today). Use the format YYYY-MM-DD.
2. Call the Agent tool with `subagent_type: "general-purpose"`, `description: "Write daily report"`, and the prompt below with DAY filled in. Wait for the result.
3. Show the report text from the result exactly as it is, then one line with the file path. Nothing else.

Prompt for the subagent:

> Write a daily standup report for DAY.
> 1. Run `todo daily DAY`. It prints the report file path, the day's Claude Code sessions (title, folder, branch, PR/MR links, the user's prompts), git commits, and TODO list changes.
> 2. Run `todo show --all --brief` for the open items.
> 3. Write the report. The user says it out loud at the daily meeting:
>    - Short sentences. Common words. Active voice. Keep the real names: PR/MR numbers, ticket IDs, project names.
>    - Group sessions about the same topic into one bullet. Use TODO section titles as topic names where they fit.
>    - Leave out small questions that led to no work (for example a quick "how does X work" question), and sessions about personal tooling (TODO, Claude setup) unless they took most of the day.
>    - State facts from the sources only. Do not guess results that the sources do not show.
>
>    Format:
>    ```
>    # Daily report DAY
>
>    ## Today
>    - <topic>: <what was done, result>        (3–6 bullets)
>
>    ## Tomorrow
>    - <next step>                              (2–5 bullets: open Active items and the next steps the sessions point to)
>
>    ## Blockers
>    - <what> — waiting on <who/what>           (or "None")
>    ```
> 4. Save it to the report file path from step 1 (create the folder if needed). Overwrite an existing file for the same day.
> 5. Return the report text and the file path. Nothing else.
