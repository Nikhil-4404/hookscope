# Hookscope project workflow

Apply the personal `project-workflow` skill when available. Core contracts live at this root: `prd.md`, `requirements.md`, `techstack.md`, `flow.md`, `status.md`; web domains are `backend.md` and `frontend.md`. `README.md` owns operator/startup instructions; `PROJECT.md` indexes the specifications.

Keep intended product scope, observed behavior, and verification evidence separate. Update affected documents alongside meaningful changes. Record the exact scope of passing checks. Browser behavior, real-provider delivery, Docker, and public-deployment readiness must remain pending until verified. Labeled simulators are permitted; synthetic measurements are not real integration performance evidence.

Use a modular monolith and existing stack unless requirements justify a change. Preserve persisted event/attempt data and introduce versioned migrations before schema evolution. Do not change credentials, publish the service, broaden access, or modify other repositories merely to adopt documentation standards.
