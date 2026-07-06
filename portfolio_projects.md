# Portfolio Projects — Citable in Applications

Public GitHub projects that tailored resumes and cover letters may reference. Everything here is real, verifiable, and public — cite freely where relevant, never embellish beyond what's written. Updated by the Friday portfolio routine after each build.

Format per entry: repo URL, one-line description, when to cite it, and a resume-ready line.

---

## agent-ops-bench
**URL:** https://github.com/neeshykha/agent-ops-bench
**What:** Single vs multi-agent benchmark on a labeled ticket triage workload. Three configurations (generalist, parallel specialists, generalist + independent QA reviewer) measured on accuracy, cost per ticket, and latency. Key results: specialists took routing 83%→97% but left severity judgment flat; the QA reviewer took severity 70%→80% and caught an under-triaged critical ticket, at $0.60 per net correction.
**Cite when:** JD or interview asks about agent orchestration, multi-agent systems, "managing agents," AI cost/quality tradeoffs, or agentic workflow design. This is the direct answer to "how do you think about agents" — with measurements. Pairs with the workforce-management framing: agent patterns are staffing decisions (generalist headcount, specialist roles, QA sampling layer).
**Resume line:** Benchmarked single-agent vs. multi-agent architectures on a labeled support triage workload, quantifying when specialist agents and QA-reviewer agents justify their added cost and latency.

## claude-triage-simulator
**URL:** https://github.com/neeshykha/claude-triage-simulator
**What:** AI ticket triage classifier (severity + routing) for IoT support, with an eval harness — 60-ticket labeled dataset, confusion matrix, under/over-triage analysis, edge-case audit. Caught 12/12 P1s; 75% severity / 87% routing accuracy.
**Cite when:** JD mentions AI evaluation, LLM output quality, AI deployment rigor, ticket triage/routing, or support AI. Especially strong for AI Engagement Manager and forward-deployed roles — it demonstrates measuring an AI system, not just shipping one.
**Resume line:** Built an LLM-based support ticket triage classifier with a full evaluation harness (confusion matrix, cost-weighted miss analysis); caught 100% of critical-severity tickets on a labeled test set.

## claude-resume-pipeline
**URL:** https://github.com/neeshykha/claude-resume-pipeline
**What:** AI-powered resume tailoring and job discovery pipeline. CLAUDE.md encodes ATS optimization logic; Python handles ATS board polling (50+ companies), composite scoring, and PDF rendering.
**Cite when:** JD mentions AI tooling implementation, workflow automation, or encoding domain expertise into AI systems. Use carefully — citing the resume pipeline *in a resume it produced* can be a clever meta-point or too cute, judge per company culture.
**Resume line:** Designed an AI job-discovery and resume-tailoring pipeline encoding ATS screening logic into a Claude instruction layer, with automated polling of 50+ company job boards.
