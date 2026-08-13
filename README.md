# ShopMind 


Welcome to the **ShopMind** e-commerce chaos testing sandbox. This repository contains a fully functional, zero-dependency, 12-microservice ecosystem designed to test distributed systems, trace request propagation, collect metrics, and evaluate GNN-based root cause analysis (RCA) models under real-world system failures.

---

## 🏗️ Architecture & Microservices

The environment is built using Nginx routers and lightweight, zero-dependency Node.js servers, making it 100% offline-ready without requiring `npm install` packages inside the containers.

### Services Mapping:
* **`frontend` (Port `3000`)**: Responsive dark-mode single page application showcasing the tech storefront, live request logs, and chaos trigger switches.
* **`api-gateway` (Port `80`)**: Nginx reverse proxy distributing prefix routes togit  backends.
* **`auth-service` (Port `3001`)**: Mock JWT credential exchange.
* **`user-service` (Port `3002`)**: Simple user profile storage.
* **`order-service` (Port `3003`)**: Orchestrator executing the transaction workflow (deducts stock $\rightarrow$ creates payment order $\rightarrow$ sends notification).
* **`payment-service` (Port `3004`)**: Test payment capture matching Razorpay API interfaces.
* **`inventory-service` (Port `3005`)**: Simulated inventory allocation check.
* **`notification-service` (Port `3006`)**: Simulated email/SMS logs.
* **`search-service` (Port `3007`)**: Workspace tech catalog containing search filters.
* **`cache` (Port `6379`)**: Redis instance for caching.
* **`postgres-primary` (Port `5432`)** & **`postgres-replica` (Port `5433`)**: Relational storage.

---

## ⚡ Telemetry & Tracing

* **Metrics (Prometheus - Port `9090`)**: Every Node service automatically maintains and exposes standard metrics (CPU usage, memory footprint, request counter, latency durations) on the `/metrics` endpoint in native Prometheus format.
* **Distributed Tracing (Jaeger - Port `16686`)**: Request trace headers (`x-trace-id` and `x-span-id`) are propagated automatically across services. Trace spans are formatted and pushed directly to Jaeger's OTLP HTTP receiver (`/v1/traces`), creating a complete cascading execution tree.

---

## 🛠️ Chaos Engine & Fault Injection

Every microservice exposes a secure `/inject-fault` POST endpoint. The following 4 fault types are supported:
1. **CPU Stress**: High loop calculations on an interval to simulate process lockups.
2. **Memory Pressure**: Continuous allocations of buffered memory to simulate memory leaks.
3. **Network Delay**: Injects artificial timeouts (`setTimeout`) before request mapping.
4. **Pod Crash**: Triggers process exits. Container auto-restart rules execute a clean recovery.

*Note: All fault injections run against a safety time-box (`duration_sec`) and automatically rollback metrics and configurations once the window expires.*

---

## 📊 GNN Data Pipeline Exporter

The `telemetry-exporter` daemon queries the Prometheus and Jaeger REST APIs every 10 seconds to generate an adjacency tree file at `telemetry-exporter/adjacency.json`. 
It records:
* Average CPU/Memory ratios per service.
* Error counts and average latency.
* Edge call weights (frequency of inter-service communication).
* Ground-truth labels of any active fault injection (essential for GNN training).
* Spearman Rank Correlation checks validating telemetry data quality.

---

## 🚀 How to Run the Project

### Prerequisites:
* Docker Desktop installed and running.

### 1. Start the Environment
Open a terminal in this directory and execute:
```powershell
docker compose up -d
```

### 2. Access Dashboards
* **E-Commerce Web Panel**: [http://localhost:3000](http://localhost:3000)
* **Jaeger Distributed Tracer**: [http://localhost:16686](http://localhost:16686)
* **Prometheus Graph Explorer**: [http://localhost:9090](http://localhost:9090)

### 3. Verification & Testing
1. Navigate to the storefront and click **Buy Now** on any workspace item.
2. Open Jaeger, select `order-service`, and search for traces. You will see a cascading tree containing **4 linked spans** covering the entire request lifecycle.
3. Go back to the dashboard, select a service and a chaos scenario (e.g. `network_delay` on `inventory-service`), and click **Inject Fault**. 
4. Perform checkouts again to monitor how downstream failures propagate back to the gateway.
