# Project Guide & Instructions

## Development Workflows
- **Build**: [Insert build command, e.g., npm run build]
- **Test**: [Insert test command, e.g., npm run test]
- **Lint**: [Insert lint command, e.g., npm run lint]

## Coding Standards & Rules
- Follow existing architectural patterns in the codebase.
- Maintain consistent naming conventions and directory structures.
- Keep components modular and write clean, documented code.

─────────────────────────────────────────────────────────────
Commit instructions — IMPORTANT
─────────────────────────────────────────────────────────────

After each phase commit using ONLY this format — no Co-Authored-By line, no 
mention of Claude or AI:

  git commit -m "$(cat <<'EOF'
  <message from phase above>
  EOF
  )"

KEEP COMMITING AFTER CHANGES
Do NOT append "Co-Authored-By: Claude" or any AI attribution. The commit should 
look exactly as if it was written by the repo owner. Also the commit if of single line, dont put a description with it.


Keep the comments minimal and use single lines/ paragraphs if need. don't ever put the dashes to get notice