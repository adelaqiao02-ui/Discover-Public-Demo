# VR Learner Report Card — Public Synthetic Demo

This package is a **public-safe demonstration variant** built from the DISCOVER Hackathon V12 prototype. **All packaged gaze records are independently generated fictional examples**; all action logs, scenario values, scoring rubrics, identities, and performance results are synthetic. No original gaze or clinical source files are included.

## What you can demo
- Admin / Group Leader / Student views using **demo-only accounts**
- Learner report card, eye-tracking summaries, fictional action timelines and fictional scoring
- Comparison between synthetic sessions, scenario views, quality summaries
- **Read-only** preview of admin configuration and rubric (editing/publishing disabled on public site)

**Important:** This is not a clinical assessment, secure authentication service, or a place for actual student records. Never upload or enter real protected information into the public site.

## Demo sign-in
- Admin: `admin` / `AdminDemo#2026`
- Group Leader: `leader_g1` / `LeaderDemo#2026`
- Student: `student1` / `StudentDemo#2026`

## Run locally
Python 3.10+:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Or on Windows, double-click `run.bat`; on macOS, use `bash run.command`.
Open http://localhost:8501.

## Deploy on Streamlit Community Cloud
1. Create a **new public GitHub repository** for this public demo only. Do not upload the original V12 ZIP or its source data.
2. Extract this ZIP, then upload the **contents of the project folder**, so `app.py` and `requirements.txt` are at the repository root.
3. Visit https://share.streamlit.io/ and sign in with GitHub.
4. Create an app for this repository, select `main`, and set the entry point to `app.py`.
5. Deploy, open the generated `.streamlit.app` URL, and test all demo roles.

This is a read-only public presentation variant. Admin changes and version publishing are intentionally unavailable. Avoid using it for real learners, even with a login screen.

## Files and provenance
- `sample data/G*_S*_PUBLIC_SYNTHETIC.csv`: fictional gaze rows made from a fixed-seed random generator, **not sampled from the real CSV**.
- `sample data/session_1_SYNTHETIC.json`, `session_2_SYNTHETIC.json`: fictional scenario templates.
- `sample data/action logs/ACTION_LOG_*_SYNTHETIC.csv`: preexisting fictional action fixtures.
- `demo_accounts.json`: demo credential hashes. Passwords above are deliberately public for this demo.

A few historical metadata labels in fixture files may reference the former V12 project structure; none indicates actual learner performance.
