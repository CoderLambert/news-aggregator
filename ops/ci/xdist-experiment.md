# CI-P01 — conservative pytest-xdist feasibility gate

This is **not** an unconditional switch to parallel pytest.

- Dedicated opt-in workflow runs only on trusted same-repo PR changes to these
  experiment files or when explicitly invoked on the default branch.
- The backend Runner (3 vCPU / 6GB) runs `-n 2 --dist=loadfile` three times,
  exercising every existing Python test root on each run.
- Pinned `pytest-xdist==3.8.0` and `execnet==2.1.1` are installed into
  their **own persistent XDG cache**, never into the production venv or
  `backend/requirements.txt`.
- Failures block benchmark completion; never convert failures to skips, rerun
  failing tests automatically, or erase existing Docker/venv caches.
- A passing benchmark is necessary but not sufficient to make xdist the
  default. Compare against the 235.37s serial baseline; confirm test counts,
  zero additional skips, memory, and repeatability. Only then move the xdist
  command into the required full CI in a separate approved change.
- Default CI (complete Python tests, production build, G1 smoke, frontend)
  remains untouched while running this experiment.
