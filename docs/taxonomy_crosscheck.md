# RCA Taxonomy Cross-Check — ShopMind Observability

This document verifies the ShopMind chaos testing framework against standard microservice Root Cause Analysis (RCA) taxonomies found in academic and industrial research (e.g., resource contention, network anomalies, dependency faults, and data-layer failures).

---

## 1. Taxonomy Comparison Matrix

| Failure Category | Taxonomy Description | ShopMind Implementation | Status |
|---|---|---|---|
| **Resource Contention** | CPU core exhaustion, memory leaks, RAM allocation thrashing, or OOM exits. | `cpu_stress` (thread spin loop) <br> `memory_pressure` (20MB buffer allocation loop) | **Supported** |
| **Network Anomalies** | Latency, packet loss, duplicate packets, or bandwidth limits. | `network_delay` (middleware timeout) | **Supported** (Latency) <br> *Packet Loss: Not Supported* |
| **Dependency Faults** | Container crash, process termination, connection drops, API timeouts. | `pod_crash` (exit code 1) <br> `1.5s Client Timeouts` (cascading 500s) | **Supported** |
| **Data-Layer Faults** | Database lock contention, slow queries, cache stampedes, pool exhaustion. | None | **Gap Identified** |

---

## 2. Detailed Mapping & Gaps

### Category 1: Resource Contention
* **Alignment**: The sandbox simulates CPU stress by pinning the single-threaded Node loop ($80\%$ load) and memory pressure by allocating $20\text{MB}$ chunks. Under our refined metrics scaling (measured relative to 512MB memory limit and single-core thread capacity), these anomalies manifest clearly as spikes to $~0.8$ CPU and memory usage in `/metrics`.

### Category 2: Network Anomalies
* **Alignment**: The sandbox simulates latency via target-side sleeps. Together with our client timeouts ($1.5\text{s}$), this correctly replicates cascading response delays and eventual HTTP 504/500 errors.
* **Gap**: We do not currently inject packet loss, corruption, or network partitioning (e.g., using `iproute2` or `iptables` rules).

### Category 3: Dependency Failures
* **Alignment**: The sandbox implements `pod_crash` (abrupt process termination) and configures Docker Compose to auto-restart the container (`restart: unless-stopped`). Our uptime watcher (`healthcheck.py`) records these transients in `uptime_log.jsonl`.

### Category 4: Data-Layer Failures (Observability Gap)
* **Gap Description**: While `postgres-primary`, `postgres-replica`, and `cache` (Redis) run inside the Docker net, the microservices do not read/write to them, nor do we scrape their engine metrics (e.g. database locks, cache hit ratios, Redis evictions).
* **Impact**: Downstream GNN models cannot learn node-failure patterns arising from database contention or cache evictions.
* **Recommendation**: In future iterations, bind database client queries to the order and user services, scrape PostgreSQL connection logs, and introduce database transaction lock injections.

---

## 3. References

1. **Silva et al. (2022)**: *"Towards a Fault Taxonomy for Microservices-Based Applications"*. In *Proceedings of the 36th Brazilian Symposium on Software Engineering* (SBES 2022), Sociedade Brasileira de Computação (SBC).
2. **Zhou et al. (2021)**: *"Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study"*. *IEEE Transactions on Software Engineering* (TSE 2021).

