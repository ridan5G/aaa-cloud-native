## Git workflow
- I am the sole contributor on this project.
- I handle all git operations myself — Claude Code only edits files.
- DO NOT run any git commands — no `git add`, `git commit`, `git push`, `git status`, `git diff`, `git checkout`, `git branch`, or any other git command.
- DO NOT create branches. All work happens directly on `main`.
- DO NOT open pull requests.
- After making file changes, SUGGEST the git commands I should run, formatted as a copy-pasteable code block.
- Use specific file paths in `git add` when possible (not `git add .`) so I can see exactly what will be staged.
- Write clear, concise commit messages describing what changed (e.g., "fix login redirect", "add dark mode toggle"). Avoid generic messages like "changes" or "update".
- If changes touch multiple unrelated areas, suggest separate commits — one per logical change.

## Other preferences
- Ask before installing new dependencies.
- Don't create new files when editing an existing one will do.
- Match the existing code style in the file you're editing.
- Don't add comments explaining obvious code.
- If you're unsure about an approach, ask before making large changes.