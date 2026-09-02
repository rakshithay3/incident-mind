# ShopMind Presentation Runbook & Live Demo Guide

This guide provides the complete presenter script, timing guidelines, and visual navigation flow for demonstrating the ShopMind microservice chaos and telemetry sandbox live to an audience or project guide.

---

## 🖥️ 1. Presenter Environment Setup

Before starting the demo, ensure Docker Desktop is running and verify that the browser tabs are opened to the following URLs:

| Dashboard | URL | Purpose |
| :--- | :--- | :--- |
| **ShopMind Storefront** | [http://localhost:3000](http://localhost:3000) | Live customer interaction, checkout simulation, chaos switches |
| **Jaeger Distributed Tracer** | [http://localhost:16686](http://localhost:16686) | Visual inspection of cascading execution spans across services |
| **Prometheus Graph Explorer** | [http://localhost:9090](http://localhost:9090) | Metric visualization (`process_cpu_usage_ratio`, error rates) |

---

## 🎯 2. Fault Selection Strategy for Live Audiences

To prevent unexpected stalls or prolonged recovery times during a live presentation, choose your demo scenario deliberately based on audience time constraints:

### 🟢 Recommended for Live Audiences: Fast Recovery (<2s)
1. **CPU Stress on `auth-service`**:
   - *Visual Impact*: Instant CPU spike to >90% on Prometheus. Request latencies increase moderately due to Node event-loop starvation.
   - *Recovery*: **<1.0 second**. Immediate thread release upon reset.
2. **Memory Pressure on `search-service`**:
   - *Visual Impact*: Heap buffer allocations consume memory footprint smoothly.
   - *Recovery*: **<1.0 second**. Buffer array is zeroed and Node garbage collection cleans memory instantly.

### 🟡 Extended Recovery (~10–15s): Causal Cascade Showcase
3. **Network Delay on `payment-service`**:
   - *Visual Impact*: Demonstrates **asymmetric RPC failure**. `order-service` (the upstream caller) hangs waiting for payment response and eventually aborts, while `payment-service` spans freeze.
   - *Recovery*: **~2–10 seconds**. Queued socket retries must drain before Jaeger latency normalizes below 100ms.
4. **Pod Crash on `inventory-service`**:
   - *Visual Impact*: Process exits with code 1. Storefront returns HTTP 500/Connection Refused. Docker auto-restart engine revives the container.
   - *Recovery*: **~10–15 seconds**. Requires container restart, process re-initialization, and Prometheus reconnect.

### 📊 Empirical Recovery Benchmark (Measured Across Stack)
The following table reflects real, automated measurements from `benchmark_demo_recovery.py`:

| Preset | Fault Scenario | Target Service | Category | Measured Settle Time |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **CPU Stress** | `auth-service` | Fast (<2s) | **0.19s** |
| **2** | **Memory Pressure** | `search-service` | Fast (<2s) | **5.41s** (with GC buffer release) |
| **3** | **Network Delay** | `payment-service` | Extended (~10–15s) | **2.32s** |
| **4** | **Pod Crash** | `inventory-service` | Extended (~10–15s) | **11.45s** (container reboot & ping) |

---

## 📋 3. Step-by-Step Presenter Script (5 Stages)

### Stage 1: Establishing Baseline Health
* **Action**: In the terminal, run:
  ```bash
  python demo_workflow.py --fault 1
  ```
* **Speaker Notes**:
  > *"Here you can see ShopMind's 12-microservice ecosystem running in Docker. Before introducing any anomaly, our automated baseline check verifies that all 7 application microservices are healthy, and their CPU and memory channels are operating at stable baseline levels."*

### Stage 2: Normal Checkout & Distributed Tracing
* **Action**: Switch to the browser at [http://localhost:3000](http://localhost:3000) and click **Buy Now** on any product, or let the CLI trigger the checkout transaction.
* **Speaker Notes**:
  > *"When a customer completes a checkout, the request enters our Nginx API Gateway, calls the order orchestrator, checks stock in inventory, and charges payment. In Jaeger at port 16686, we can see the entire execution tree with linked spans and sub-millisecond latencies."*

### Stage 3: Chaos Perturbation
* **Action**: Press `Enter` in the CLI to inject the chosen fault (e.g., CPU stress on `auth-service`).
* **Speaker Notes**:
  > *"Now, we programmatically perturb the cluster using our built-in chaos engine. Unlike arbitrary script kills, ShopMind injects reproducible faults conforming to empirical microservice failure taxonomies (Silva et al. 2022, Zhou et al. 2021)."*

### Stage 4: Telemetry Cascade & GNN Graph Capture
* **Action**: Observe the live terminal output showing the perturbed node feature vector.
* **Speaker Notes**:
  > *"Notice how the anomaly propagates through the graph. The target service's telemetry immediately shifts, showing elevated CPU utilization and degraded throughput. Our export pipeline captures this exact snapshot as an adjacency matrix and node feature vector for the Graph Neural Network (GNN) root cause analysis model."*

### Stage 5: Dynamic Settle & Emergency Reset
* **Action**: Press `Enter` to trigger the cluster rollback.
* **Speaker Notes**:
  > *"Finally, we trigger the rollback. Rather than assuming the cluster has recovered after a static delay, ShopMind runs dynamic settle checks under load to verify that metrics and latencies have fully stabilized before declaring the cluster clean. Notice that recovery completes cleanly in seconds."*

---

## 🚨 4. Emergency Procedures (Audience Fallback)

If a service appears sluggish or an audience-selected fault causes lingering latency:

1. **Immediate Reset via Terminal**:
   Open a separate terminal window and execute:
   ```bash
   python reset_state.py
   ```
   *This fires concurrent `/reset` calls to all services, wipes any active chaos intervals, and restarts any unresponsive containers on the host.*

2. **Hard Docker Restart (Worst-Case)**:
   If Docker Desktop experienced a host freeze:
   ```bash
   docker restart shopmind-api-gateway shopmind-order-service shopmind-auth-service
   ```
