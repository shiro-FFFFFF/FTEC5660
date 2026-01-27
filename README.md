# FTEC5660 &mdash; Agentic AI for Business and FinTech

This repository captures my coursework submissions for **FTEC5660 Agentic AI for Business and FinTech** at CUHK. Each homework folder contains the deliverables submitted for grading (reports, notebooks, slide decks, etc.), along with any supporting code or documentation.

## Repository structure

```
FTEC5660/
├── homeworks/
│   └── hw1/
│       ├── HW1.pdf
│       ├── notebook.ipynb
│       └── report.pdf
└── README.md
```

- `homeworks/hwN/`: one directory per assignment (e.g., `hw1`, `hw2`, ...).
- Within each homework directory, keep the authoritative submission artifacts plus optional scratch work or datasets in clearly named subfolders (`data/`, `scripts/`, `figures/`, etc.).

## Working on an assignment

1. **Create a branch/folder**: start from `homeworks/hwN/` and duplicate the previous homework's structure if it helps maintain consistency.
2. **Set up your environment**:
   - All notebooks run in **Google Colab**, so no need to create local virtual environments (venv/conda).
   - Keep dependencies documented inside the notebook/report; rely on `pip install ...` cells within Colab when extra packages are needed.
   - The Gemini API key is stored in Colab Secrets—retrieve it at runtime (e.g., `from google.colab import userdata; userdata.get('GEMINI_API_KEY')`).
3. **Develop & validate**:
   - Use Jupyter Notebook or VS Code's notebook interface for experimentation.
   - Keep intermediate datasets lightweight or git-ignore large/raw files when necessary.
4. **Generate submission artifacts**: export final notebooks to PDF (if required), produce the written report, and save any slide decks or demos in the same `hwN` folder.
5. **Self-check before submission**:
   - ✅ All code cells executed top-to-bottom without errors.
   - ✅ Key findings/explanations captured in the report.
   - ✅ File names follow the course submission convention (e.g., `HW1.pdf`).

## Adding future homeworks

1. Create a new folder `homeworks/hwN`.
2. Copy the template files you need (e.g., a blank notebook, report skeleton).
3. Update this README if the structure or tooling changes materially.

## Tips & notes

- Maintain clear version history (Git commits) so you can reference earlier iterations when writing reports.
- Document external data sources or APIs directly inside notebooks for transparency and reproducibility.
- If group work is required, note collaborators and contribution splits in each homework's README or report front matter.

## Questions

For course-related support, refer to the official FTEC5660 communication channels (Blackboard, Piazza, or email). For repository or tooling issues, leave notes in commit messages or a `README` inside the relevant homework folder.
