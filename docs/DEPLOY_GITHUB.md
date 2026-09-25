# Pushing to GitHub (prepared, not executed)

This repo has no GitHub remote configured yet (`git remote -v` is empty) —
by design, per CLAUDE.md's "everything runs locally" rule, nothing has been
pushed anywhere automatically. These are the exact steps to do it yourself,
whenever you're ready. A GitHub repo is also the prerequisite for the
Render Blueprint deploy — see [DEPLOY_RENDER.md](DEPLOY_RENDER.md).

## 1. Create an empty repository on GitHub

Go to <https://github.com/new> and create a repository named
**`lehar-early-warning`**:
- Owner: your account
- Visibility: your choice (public or private — Render's free Blueprint
  deploy works with either once connected)
- **Do NOT** initialize with a README, `.gitignore`, or license — this
  repo already has all of those; an empty remote avoids a merge conflict
  on the very first push.

## 2. Push this local repo

Run these three commands from the project root
(`C:\Users\user\Desktop\Smart Irrigation`), replacing `<your-username>`:

```
git remote add origin https://github.com/<your-username>/lehar-early-warning.git
git branch -M main
git push -u origin main
```

If you use SSH instead of HTTPS for GitHub, use
`git@github.com:<your-username>/lehar-early-warning.git` for the first
command instead.

## 3. Verify

Refresh the GitHub repo page — you should see the full file tree,
`README.md` rendered on the repo home page, and the CI badge (top of
`README.md`) starting to resolve once `.github/workflows/ci.yml` runs on
this first push (Actions tab).

## Notes

- **Secrets stay out of the push.** `.env`, `backend/.env`, and anything
  matching `*.db`/`*.sqlite*` are gitignored (verified in Phase 11's
  secrets audit, `docs/SECURITY.md`) — nothing in this push exposes your
  local `JWT_SECRET` or Groq API key.
- **Large files.** The committed model artifacts under `backend/ml/model/`
  and the training dataset under `data/` are already tracked in git from
  earlier phases (a few MB each, no Git LFS needed) — the push includes
  them as normal, no extra step required.
- After this push, `README.md`'s CI badge and `render.yaml`'s Blueprint
  deploy both become usable — neither works against a repo that only
  exists locally.
