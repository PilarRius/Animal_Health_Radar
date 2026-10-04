# WOAH Datathon 2026 — Submission checklist

Official instructions: https://data-integration-department-woah.github.io/WOAH-Datathon/submission.html  
Deadline: **31 October 2026** (no commits after this date).

## Required contents

1. Analytical pipeline (this repository)  
2. Technical report — `docs/TECHNICAL_REPORT.md`  
3. README with reproduction steps — `README.md`  
4. **Signed** Open Source Sharing Agreement PDF at repo root:

   `Open_Source_Sharing_Agreement_signed.pdf`

   Download the template from the WOAH submission page. The Team Leader fills names/roles, signs, and commits the PDF. Without it the submission is incomplete.

## How to submit

1. Host as a **private** GitHub repository.  
2. Add the organisation **`diad-woah`** as a collaborator with at least **read** access.  
3. That grant **is** the submission — no separate form.  
4. Freeze the repo (including the signed PDF) by the deadline.

## Licence

Signing the agreement confirms release under the **MIT** licence for the submission.

## Pre-flight

- [ ] `project.data_mode: pilot` and INFUR/SMR files present under `data/raw/`  
- [ ] `python scripts/run_pipeline.py` completes  
- [ ] `reports/validation/metrics.json` and `lead_time.json` exist  
- [ ] `shiny run app.py` opens Intro first  
- [ ] Technical report reviewed for honest limitations  
- [ ] `Open_Source_Sharing_Agreement_signed.pdf` at root  
- [ ] `diad-woah` invited  
