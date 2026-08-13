# Academic Failure Taxonomy Alignment — ShopMind Sandbox

This document maps the fault injections supported in the ShopMind sandbox to established academic failure taxonomies for microservice environments, validating the dataset's representativeness for downstream GNN evaluations.

---

## 1. Mappings to Academic Literature

The ShopMind chaos engine supports four injection fault classes. These align directly with the empirical findings of the following two benchmark surveys:

### A. Silva et al. (SBES 2022)
* **Citation**: *Silva, A., et al. "A Taxonomy of Microservice Failures: Empirical Study and Classification"*, Brazilian Symposium on Software Engineering (SBES), 2022.
* **Scope**: Catalogs 117 distinct microservice faults, classified across 6 non-functional requirements (Availability, Reliability, Performance, Security, Maintainability, Portability) and 11 system characteristics.

### B. Zhou et al. (IEEE TSE 2021)
* **Citation**: *Zhou, X., et al. "Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study"*, IEEE Transactions on Software Engineering (TSE), 2021.
* **Scope**: A comprehensive empirical survey classification of root causes, failure propagation, and telemetry diagnostics across large-scale industrial microservices.

---

## 2. Fault Taxonomy Correspondence Matrix

| ShopMind Fault Class | Silva et al. (SBES 2022) Alignment | Zhou et al. (IEEE TSE 2021) Alignment | Simulation Mechanism in Sandbox |
| :--- | :--- | :--- | :--- |
| **`cpu_stress`** | **Performance Faults** <br>*(Resource Saturation)* | **Hardware / OS Layer** <br>*(Compute resource exhaustion)* | Spawns a high-frequency `setInterval` loop performing dense float multiplication (`Math.random()`), locking Node's single-threaded event loop. |
| **`memory_pressure`** | **Reliability / Portability** <br>*(V8 Heap Leak / GC Thrashing)* | **Application Layer** <br>*(Leak anomalies, process memory limit exhaustion)* | Progressively allocates memory buffers in the heap, causing garbage collection thrashing and eventual V8 heap out-of-memory states. |
| **`network_delay`** | **Reliability / Performance** <br>*(Cascading Latency / Slow Response)* | **Network / Communication Layer** <br>*(Network delays, RPC timeout failures)* | Introduces a 2000ms delay in response routing via custom middleware, triggering upstream client-side circuit breakers and 1.5s gateway timeouts. |
| **`pod_crash`** | **Availability Faults** <br>*(Container crashes, termination)* | **Infrastructure Layer** <br>*(Pod termination, container restarts)* | Sits in a sleep loop for 3 seconds then issues a direct `process.exit(1)`, forcing Docker to stop the container and trigger healthcheck status changes. |

---

## 3. Telemetry Symptom Mappings

The telemetry values exported in `adjacency.json` map directly to the failure diagnostics described by Zhou et al.:

1. **`cpu_pct` & `mem_pct`**: Track compute resource exhaustion trends. Essential for classifying `cpu_stress` and `memory_pressure` anomalies.
2. **`mean_latency_ms` & `p99_latency_ms`**: Capture RPC delay propagation. Critical for identifying `network_delay` cascades and queuing blockages.
3. **`error_rate`**: Tracks connection termination and unhandled routing faults. Directly maps to service availability and cascading failures during `pod_crash` events.
