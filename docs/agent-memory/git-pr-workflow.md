# Git pr workflow

_User wants feature branches committed, pushed, and a PR compare link sent; they create and merge PRs themselves_

Commit at milestones on a branch, push to github.com/priyansh1210/the-fly-colony, and give the user the "open a PR" compare link. The user creates and merges the PRs themselves, so don't run `gh pr create`.

**Why:** The user said so on 2026-10-12: "Commit and push and send me the link to open the PR - I will create them and merge them".
**How to apply:** Never commit straight to main. Use the branch → push → send `https://github.com/priyansh1210/the-fly-colony/compare/main...<branch>?expand=1` flow. Related: [fly-colony-project-setup](fly-colony-project-setup.md)
