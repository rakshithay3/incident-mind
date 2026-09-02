# Section 5.1: ShopMind Microservice Benchmark & Chaos Testbed

## 5.1 Experimental Testbed Architecture

To rigorously evaluate Graph Neural Network (GNN) architectures and autonomous multi-agent systems on microservice root cause analysis (RCA), we designed and implemented **ShopMind**—a full-lifecycle, containerized e-commerce testbed. The testbed models an enterprise transaction workflow with zero external cloud dependencies, realistic inter-service call graphs, and mathematically grounded fault perturbations.

---

### 5.1.1 Architectural Topology & Runtime Engine
The ShopMind environment comprises **12 decoupled services** organized in a directed acyclic dependency graph:
* **Edge Ingress**: An Nginx API Gateway (`shopmind-api-gateway`, Port 80) acting as the single reverse proxy ingress, alongside an interactive storefront SPA (`shopmind-frontend`, Port 3000).
* **Core Business Logic (7 Application Services)**: Implemented as lightweight, zero-dependency Node.js 20 microservices:
  1. `auth-service` (Port 3001): JWT issuance and Redis session validation.
  2. `user-service` (Port 3002): Customer profile management and relational lookups.
  3. `order-service` (Port 3003): Core orchestrator executing checkout sagas.
  4. `payment-service` (Port 3004): Payment capture matching Razorpay REST interfaces.
  5. `inventory-service` (Port 3005): Stock allocation and relational consistency locking.
  6. `notification-service` (Port 3006): Asynchronous dispatch simulation for email/SMS.
  7. `search-service` (Port 3007): Product catalog query engine with replica DB caching.
* **Stateful Storage & Caching**: PostgreSQL 16 configured with streaming replication (`postgres-primary` on Port 5432 and read-only `postgres-replica` on Port 5433), combined with a Redis 7 cache (`shopmind-cache`, Port 6379).
* **Distributed Observability Engine**:
  * **Traces**: Every intra-service HTTP request propagates W3C standard distributed context headers (`x-trace-id`, `x-span-id`). Microservices export structured trace spans directly via the OpenTelemetry HTTP protocol (`/v1/traces`) to an in-cluster **Jaeger** tracer (Port 16686).
  * **Metrics**: Every service continuously aggregates internal system resource usage and exposes native **Prometheus** metrics (`/metrics`, Port 9090), including CPU process utilization (`process_cpu_usage_ratio`), RSS heap memory footprint (`process_memory_usage_ratio`), and HTTP status request counters.

---

### 5.1.2 Chaos Perturbation Taxonomy & Theoretical Mapping
Rather than relying on non-deterministic process termination, ShopMind formalizes failure injection against published empirical microservice fault taxonomies, specifically mapping each perturbation to categories identified by **Silva et al. (2022)** and **Zhou et al. (2021)**:

| Failure Mode | Target Manifestation | Taxonomy Mapping (Silva et al. 2022; Zhou et al. 2021) | Injected Mechanism |
| :--- | :--- | :--- | :--- |
| **CPU Stress** | Thread starvation, event-loop blocking | *Computational Exhaustion / Resource Starvation* | Non-blocking periodic spin loops occupying 80ms of every 100ms interval. |
| **Memory Pressure** | Heap memory exhaustion, GC stalls | *Memory Leak / Memory Exhaustion* | Progressive 20MB buffer chunk allocation every 200ms up to container RSS limits. |
| **Network Delay** | Downstream latency spike, queue buildup | *Communication Degradation / Network Latency* | Synthetic middleware sleep (`delayMs = 2000`) injected prior to request handling. |
| **Pod Crash** | Container unavailability, unreachability | *Instance Failure / Process Crash* | Controlled `process.exit(1)` triggering Docker daemon auto-recovery. |

Each perturbation is exposed via an authenticated `/inject-fault` control endpoint parameterized by `duration_sec`, maintaining an explicit ground-truth state label throughout the active chaos window.

---

### 5.1.3 Telemetry Integrity, Settle-Check Evolution & Anti-Contamination
A recognized hazard in chaos benchmark generation is **cross-incident contamination**, where latent latency queues or residual memory pressure from incident $k$ bleed into the baseline window of incident $k+1$, generating spurious root-cause correlations.

Through iterative stress testing, we developed an active, metrics-aware isolation protocol:
1. **Dynamic Metrics-Aware Settle Verification**: Following fault rollback, the cluster does not rely on arbitrary sleep intervals. Instead, `verify_settle()` continuously drives low-intensity storefront load (~10 req/s) while evaluating live telemetry:
   $$\text{Settled} \iff (\text{CPU} < 0.15) \land (\text{Mean Latency} < 100.0\text{ ms}) \land (\text{Error Rate} < 0.10)$$
   Under empirical benchmark runs, clean baseline stabilization occurs in **0.19s** for CPU stress, **2.32s** for network delay, and **11.45s** for crashed containers requiring daemon restart.
2. **Crash Grace Period**: Containers recovering from a `pod_crash` are subjected to a mandatory **15-second stabilization cooldown** to allow the Node runtime to re-establish database connection pools before baseline recording resumes.
3. **Bounded Telemetry History Log Rotation**: High-frequency metric scrapers rotate historical log structures atomically (truncating from 2,000 down to 1,000 entries), guaranteeing bounded memory footprints and preventing container out-of-memory terminations during long multi-hour benchmark sweeps.

---

### 5.1.4 Asymmetric RPC Failure Propagation
A critical phenomenon observed and modeled in ShopMind is **asymmetric RPC failure propagation**. 

During downstream network delay injection on a dependency (e.g., `payment-service` subjected to `delayMs = 2000`):
* **Upstream Orchestrator (`order-service`)**: Latency climbs significantly ($>1200\text{ ms}$) as pending promises accumulate in the Node event loop, with client-side timeout aborts triggering HTTP 500 error cascades.
* **Downstream Target (`payment-service`)**: Displays seemingly idle span durations (0.0ms) or dropped telemetry when client connections are severed before responses are dispatched.

Documenting and preserving this structural asymmetry in the testbed prevents naive heuristics from assuming that the node exhibiting the highest latency is invariably the root cause.

---

### 5.1.5 Benchmark Dataset & Export Boundary Protocol
ShopMind generated an official, reproducible evaluation dataset comprising **100 independent incidents** governed by a deterministic schedule (`evaluation_schedule.json`) across all 28 service-fault permutations.

To interface cleanly with downstream Graph Neural Network (GNN) loaders and AI reasoning agents, ShopMind defines a **two-stage export boundary**:
1. **Raw Telemetry Stream (`datasets/incident_XXX/`)**: Preserves literal `null` representations whenever a container is unreachable or an HTTP probe times out. This maintains 100% ground-truth fidelity, distinguishing between an authentic zero-value metric (e.g., 0.0% CPU) and a complete communication blackout.
2. **Packaging & Alignment Adapter (`package_evaluation.py`)**: 
   * **Dynamic Peak-Anomaly Snapshot Selection**: Computes the system-wide deviation from baseline across the failure window, selecting the single second exhibiting maximum anomaly severity rather than relying on arbitrary static timestamp offsets.
   * **Tensor Coercion Flexibility**: Provides boundary-level translation from ShopMind internal naming (`cpu_pct`, `mean_latency_ms`) to standardized evaluation schemas (`cpu`, `latency`), offering configurable missing-data proxies (carrying forward historical last-known-good readings or falling back to baseline averages) to prevent `float(None)` ingestion exceptions in downstream PyTorch tensor pipelines.
