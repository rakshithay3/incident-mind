const http = require('http');
const fs = require('fs');
const path = require('path');

const PROM_URL = process.env.PROMETHEUS_URL || 'http://prometheus:9090';
const JAEGER_URL = process.env.JAEGER_URL || 'http://jaeger:16686';
const EXPORT_PATH = process.env.EXPORT_PATH || '/usr/src/app/adjacency.json';

const services = [
  'auth-service',
  'user-service',
  'order-service',
  'payment-service',
  'inventory-service',
  'notification-service',
  'search-service'
];

// Helper to query REST endpoints via native http
function httpGetJson(urlStr) {
  return new Promise((resolve, reject) => {
    http.get(urlStr, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(data);
        }
      });
    }).on('error', (err) => reject(err));
  });
}

// Helper to calculate Spearman Rank Correlation
function calculateSpearman(x, y) {
  const n = x.length;
  if (n !== y.length || n === 0) return 0;
  if (n === 1) return 1;

  const addRanks = (arr) => {
    const sorted = arr.map((val, idx) => ({ val, idx })).sort((a, b) => a.val - b.val);
    let rank = 1;
    for (let i = 0; i < n; i++) {
      if (i > 0 && sorted[i].val !== sorted[i - 1].val) {
        rank = i + 1;
      }
      sorted[i].rank = rank;
    }
    const ranked = new Array(n);
    sorted.forEach(item => {
      ranked[item.idx] = item.rank;
    });
    return ranked;
  };

  const xRanks = addRanks(x);
  const yRanks = addRanks(y);

  let sumDiffSq = 0;
  for (let i = 0; i < n; i++) {
    sumDiffSq += Math.pow(xRanks[i] - yRanks[i], 2);
  }

  return 1 - (6 * sumDiffSq) / (n * (n * n - 1));
}

let cachedFault = null;
let cachedFaultTime = 0;

async function queryTelemetry() {
  console.log('Querying telemetry data...');
  const nodes = [];
  const edges = [];

  // 1. Query CPU & Memory from Prometheus
  const cpuMap = {};
  const memMap = {};

  try {
    const cpuRes = await httpGetJson(`${PROM_URL}/api/v1/query?query=process_cpu_usage_ratio`);
    if (cpuRes && cpuRes.status === 'success' && cpuRes.data && cpuRes.data.result) {
      for (const item of cpuRes.data.result) {
        const instance = item.metric.instance; // e.g. "auth-service:3001"
        if (instance) {
          const serviceName = instance.split(':')[0];
          cpuMap[serviceName] = parseFloat(item.value[1]);
        }
      }
    }
  } catch (e) {
    console.error('Error fetching CPU from Prometheus:', e.message);
  }

  try {
    const memRes = await httpGetJson(`${PROM_URL}/api/v1/query?query=process_memory_usage_ratio`);
    if (memRes && memRes.status === 'success' && memRes.data && memRes.data.result) {
      for (const item of memRes.data.result) {
        const instance = item.metric.instance;
        if (instance) {
          const serviceName = instance.split(':')[0];
          memMap[serviceName] = parseFloat(item.value[1]);
        }
      }
    }
  } catch (e) {
    console.error('Error fetching Memory from Prometheus:', e.message);
  }

  // 2. Query Jaeger for each service's traces (latency & error rate)
  const nodeTelemetry = {};
  for (const service of services) {
    let totalSpans = 0;
    let errorSpans = 0;
    let sumDuration = 0;
    let durations = [];
    let entrypointCalls = 0;

    try {
      const tracesRes = await httpGetJson(`${JAEGER_URL}/api/traces?service=${service}&lookback=60s`);
      if (tracesRes && tracesRes.data) {
        for (const trace of tracesRes.data) {
          const spans = trace.spans || [];
          const processes = trace.processes || {};

          for (const span of spans) {
            const proc = processes[span.processID];
            if (proc && proc.serviceName === service) {
              totalSpans++;
              const durationMs = span.duration / 1000;
              sumDuration += durationMs;
              durations.push(durationMs);

              // Check error status in tags
              const isError = (span.tags || []).some(tag =>
                (tag.key === 'error' && (tag.value === true || tag.value === 'true')) ||
                (tag.key === 'otel.status_code' && tag.value === 'ERROR')
              );
              if (isError) {
                errorSpans++;
              }

              // Check if it's a top-level span and not metrics/health
              const opName = span.operationName || '';
              const isMetricsOrHealth = opName.includes('/metrics') || opName.includes('/health') || opName.includes('/fault-status');
              const hasParent = span.references && span.references.length > 0;
              if (!hasParent && !isMetricsOrHealth) {
                entrypointCalls++;
              }
            }
          }
        }
      }
    } catch (e) {
      console.error(`Error querying Jaeger traces for ${service}:`, e.message);
    }

    let meanLatency = 0.0;
    let p99Latency = 0.0;
    let errorRate = 0.0;

    if (totalSpans > 0) {
      meanLatency = sumDuration / totalSpans;
      errorRate = errorSpans / totalSpans;

      durations.sort((a, b) => a - b);
      const p99Idx = Math.floor(durations.length * 0.99);
      p99Latency = durations[p99Idx];
    }

    nodeTelemetry[service] = {
      errorRate,
      meanLatency,
      p99Latency,
      entrypointCalls
    };

    nodes.push({
      service_id: service,
      cpu_pct: parseFloat((cpuMap[service] || 0.0).toFixed(4)),
      mem_pct: parseFloat((memMap[service] || 0.0).toFixed(4)),
      error_rate: parseFloat(errorRate.toFixed(4)),
      mean_latency_ms: parseFloat(meanLatency.toFixed(2)),
      p99_latency_ms: parseFloat(p99Latency.toFixed(2))
    });
  }

  // 3. Query Edge call weights (Jaeger dependencies & entrypoints)
  for (const service of services) {
    const count = nodeTelemetry[service] ? nodeTelemetry[service].entrypointCalls : 0;
    if (count > 0) {
      edges.push({
        source: 'api-gateway',
        target: service,
        call_count: count
      });
    }
  }

  try {
    const depRes = await httpGetJson(`${JAEGER_URL}/api/dependencies?endTs=${Date.now()}&lookback=60000`);
    if (depRes && depRes.data) {
      for (const edge of depRes.data) {
        if (edge.parent && edge.child && edge.parent !== edge.child) {
          edges.push({
            source: edge.parent,
            target: edge.child,
            call_count: edge.callCount
          });
        }
      }
    }
  } catch (e) {
    console.error('Error fetching dependencies from Jaeger:', e.message);
  }

  // 4. Query active fault injection state from services (with fallback caching)
  let activeFaultInfo = {
    active: false,
    fault_type: "",
    target_service: "",
    injected_at: "",
    scheduled_duration_sec: 0,
    auto_rollback: true
  };
  let groundTruthRootCause = "";

  const portMap = {
    'auth-service': 3001,
    'user-service': 3002,
    'order-service': 3003,
    'payment-service': 3004,
    'inventory-service': 3005,
    'notification-service': 3006,
    'search-service': 3007
  };

  let foundActiveFault = false;
  for (const service of services) {
    const port = portMap[service];
    if (!port) continue;
    try {
      const statusUrl = `http://${service}:${port}/api/fault-status`;
      const faultStatus = await httpGetJson(statusUrl);
      if (faultStatus && faultStatus.active) {
        activeFaultInfo = {
          active: true,
          fault_type: faultStatus.fault_type,
          target_service: faultStatus.target_service,
          injected_at: faultStatus.injected_at,
          scheduled_duration_sec: faultStatus.scheduled_duration_sec,
          auto_rollback: faultStatus.auto_rollback
        };
        groundTruthRootCause = service;
        cachedFault = { ...activeFaultInfo };
        cachedFaultTime = Date.now();
        foundActiveFault = true;
        break;
      }
    } catch (e) {
      // Service failed to respond (could be down due to pod_crash)
    }
  }

  // If no active fault was successfully polled, check the memory cache
  // (essential for pod_crash scenarios where the service goes temporarily offline)
  if (!foundActiveFault && cachedFault) {
    const elapsedSec = (Date.now() - cachedFaultTime) / 1000;
    if (cachedFault.scheduled_duration_sec === 0 || elapsedSec < cachedFault.scheduled_duration_sec) {
      activeFaultInfo = { ...cachedFault };
      groundTruthRootCause = cachedFault.target_service;
    } else {
      cachedFault = null;
    }
  }

  // 5. Spearman Correlation Checks (CPU vs Mean Latency)
  const currentCpus = nodes.map(n => n.cpu_pct);
  const currentLatencies = nodes.map(n => n.mean_latency_ms);
  const correlation = calculateSpearman(currentCpus, currentLatencies);
  console.log(`Data quality validation: Spearman Correlation (CPU vs Latency) = ${isNaN(correlation) ? '0.000' : correlation.toFixed(3)}`);

  const payload = {
    timestamp: new Date().toISOString(),
    nodes,
    edges,
    fault_injection: activeFaultInfo,
    ground_truth_root_cause: groundTruthRootCause
  };

  try {
    fs.writeFileSync(EXPORT_PATH, JSON.stringify(payload, null, 2));
    console.log(`Successfully exported GNN payload to ${EXPORT_PATH}`);
  } catch (err) {
    console.error(`Failed to write export JSON: ${err.message}`);
  }
}

setInterval(queryTelemetry, 10000);
queryTelemetry();
