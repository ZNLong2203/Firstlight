# Declaration

Reused components, external data and AI tools used in Firstlight, as the hackathon rules require.

## What existed before the build window

The build window is 17–31 October 2026. Before it, between 7 and 16 October, the team did the following:

- **Research and design:** the problem space, the architecture, and the documentation in `docs/`, including its diagrams.
- **Repository tooling:** git hooks, `compose.yaml`, Dockerfiles, `Makefile`, the deploy and bootstrap scripts, the backup job and the CI workflow.
- **A service skeleton:** a health endpoint, JSON logging, empty `api`, `brain` and `edge` entry points, and a placeholder console page.

None of this contains solution logic. Two throwaway experiments were also run: Toto forecasting on a synthetic oxygen curve, and a comparison of Gemini embedding models. They are not part of this repository.

Everything that implements the solution was written from 17 October onward, and the commit history shows the dates: the pond simulator, ingest, forecasting, the evidence engine, playbooks, the command bus, verification, the investigator and the console.

## Open-source components

| Component | Licence | Used for |
|---|---|---|
| FastAPI, Uvicorn | MIT, BSD-3-Clause | HTTP API |
| PyMongo | Apache-2.0 | MongoDB driver |
| Pydantic, pydantic-settings | MIT | models and settings |
| httpx | BSD-3-Clause | HTTP client (gateways, Datadog API) |
| ddtrace, datadog | Apache-2.0 / BSD-3-Clause, BSD-3-Clause | APM, LLM Observability, DogStatsD |
| google-genai | Apache-2.0 | Gemini client (Vertex AI) |
| React, Vite | MIT | console |
| Apache ECharts | Apache-2.0 | charts in the console |
| Tailwind CSS | MIT | console styling |
| TypeScript | Apache-2.0 | console |
| @datadog/browser-rum | Apache-2.0 | Real User Monitoring |
| Caddy | Apache-2.0 | HTTPS reverse proxy |
| nginx | BSD-2-Clause | static console |
| Datadog Agent | Apache-2.0 | telemetry collection |
| `mongodb/mongodb-atlas-local` image | MongoDB, Inc. terms | MongoDB 8.0 with Atlas Search and Vector Search |
| Material Symbols | Apache-2.0 | icons in the documentation diagrams |
| Simple Icons | CC0-1.0 | brand logos in diagrams (the marks belong to their owners) |
| Inter, JetBrains Mono | SIL OFL 1.1 | fonts in diagrams |
| Be Vietnam Pro, Fraunces, JetBrains Mono | SIL OFL 1.1 | fonts in the console, loaded from Google Fonts |

Components added later are listed here when they are added.

## Data

No external dataset is included. All pond, sensor and gateway data is synthetic, produced by the simulator's physics model. No personal, production or regulated data is used anywhere: not in MongoDB, Datadog, the repository or the demo video.

The oxygen thresholds come from published sources:

- Global Seafood Alliance, *Water quality standards: dissolved oxygen*: ≥ 5 mg/L in intensive white-leg shrimp systems, stress below 3 mg/L.
- Embrapa, *Pesquisa Agropecuária Brasileira* 2009 (oxygen consumption of *L. vannamei* in biofloc): lethal levels reached in under an hour without aeration.

The estimate of what a pond's shrimp are worth uses published figures, cited in full in `src/firstlight/core/economics.py`:

- farm-gate prices by size: dealer quotes collected by tepbac.com on 16/10/2026;
- stocking, survival, growth, pond size and feed conversion in lined Mekong Delta ponds: FAO Fisheries and Aquaculture Circular 1194 (2019); Hiền et al., *Vietnam Journal of Agricultural Science and Technology* 5(126), 2021; Võ Nam Sơn et al., *CTU Journal of Science* 55(1B), 2019; the Can Tho University biofloc guide;
- seed and feed prices: tepbac.com, October 2026.

## AI tools

| Tool | Where | Role |
|---|---|---|
| Claude Code (Anthropic, Claude Opus 5.5; research subagents on Claude Sonnet 5.5) | development | research, design, code and documentation, directed and reviewed by the team |
| Gemini on Vertex AI: `gemini-3.8-flash`, fallback `gemini-3.5-flash` | runtime | the investigator's explanation, the farmer's message and postmortem drafts; never decides an action |
| Gemini on Vertex AI: `gemini-embedding-2` | runtime | embeddings for incident memory |
| Toto (Datadog, open weights) | evaluation only | compared with the trend computed in MongoDB on the simulator's physics, and left out of the running system (see [Architecture](ARCHITECTURE.md#8-technology-choices)) |

The team understands and can explain every part of the solution.
