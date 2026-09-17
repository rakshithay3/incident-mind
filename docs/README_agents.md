# IncidentMind-LLM

IncidentMind-LLM is a multi-agent incident investigation and Root Cause Analysis (RCA) pipeline.

The project analyzes incident evidence from:

- Application/service logs
- Service performance metrics
- Git code changes

The evidence is processed by specialized agents and combined into a final RCA report.

---

## Project Overview

IncidentMind follows a multi-agent investigation workflow:

```text
Incident
   │
   ▼
Dispatch Action
   │
   ▼
Specialist Agents
   ├── Log Agent
   ├── Metrics Agent
   └── Code Agent
   │
   ▼
Evidence Bundle
   │
   ▼
Report Agent
   │
   ▼
Final RCA Report