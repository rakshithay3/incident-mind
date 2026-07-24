
const http = require('http');
const url = require('url');
const crypto = require('crypto');
const os = require('os');
const faultInjector = require('./fault-injector');

let lastCpuUsage = process.cpuUsage();
let lastCpuTime = process.hrtime();

function getCpuUsageRatio() {
  const elapCpuUsage = process.cpuUsage(lastCpuUsage);
  const elapTime = process.hrtime(lastCpuTime);
  
  lastCpuUsage = process.cpuUsage();
  lastCpuTime = process.hrtime();
  
  const elapTimeMS = elapTime[0] * 1000 + elapTime[1] / 1000000;
  if (elapTimeMS === 0) return 0.0;
  const elapUserMS = elapCpuUsage.user / 1000;
  const elapSystMS = elapCpuUsage.system / 1000;
  const cpuPercent = (elapUserMS + elapSystMS) / elapTimeMS;
  
  return Math.min(1.0, Math.max(0.0, cpuPercent));
}

function getMemoryUsageRatio() {
  const rss = process.memoryUsage().rss;
  const containerLimit = 512 * 1024 * 1024; // 512MB
  return Math.min(1.0, Math.max(0.0, rss / containerLimit));
}

const PORT = process.env.PORT || 3004;
const SERVICE_NAME = process.env.SERVICE_NAME || 'payment-service';

// Simple metric state
const requestCounter = {};
const durationBuckets = {};

function incMetric(method, route, code) {
  const key = `method="${method}",route="${route}",status_code="${code}"`;
  requestCounter[key] = (requestCounter[key] || 0) + 1;
}

// Generate traces to Jaeger (OTLP JSON)
function sendSpan(name, traceId, spanId, parentSpanId, startTime, durationMs, statusCode = 200) {
  const startTimeUnixNano = BigInt(startTime) * 1000000n;
  const endTimeUnixNano = BigInt(startTime + Math.floor(durationMs)) * 1000000n;

  const payload = {
    resourceSpans: [{
      resource: {
        attributes: [{ key: 'service.name', value: { stringValue: SERVICE_NAME } }]
      },
      scopeSpans: [{
        spans: [{
          traceId: traceId,
          spanId: spanId,
          parentSpanId: parentSpanId || undefined,
          name: name,
          kind: 1, // SPAN_KIND_INTERNAL
          startTimeUnixNano: startTimeUnixNano.toString(),
          endTimeUnixNano: endTimeUnixNano.toString(),
          status: { code: statusCode >= 400 ? 2 : 1 }
        }]
      }]
    }]
  };

  const body = JSON.stringify(payload);
  const req = http.request({
    hostname: 'jaeger',
    port: 4318,
    path: '/v1/traces',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body)
    }
  }, (res) => {
    res.resume();
  });
  req.on('error', () => {});
  req.write(body);
  req.end();

  return { traceId: traceId, spanId: spanId };
}

// Helper to make outgoing HTTP requests with tracing propagation
function callService(serviceUrl, method, payload = {}, traceHeaders = {}) {
  return new Promise((resolve, reject) => {
    const parsedUrl = url.parse(serviceUrl);
    const body = method !== 'GET' ? JSON.stringify(payload) : '';
    
    const options = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port,
      path: parsedUrl.pathname + (parsedUrl.search || ''),
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'x-trace-id': traceHeaders.traceId || '',
        'x-span-id': traceHeaders.spanId || '',
        ...((method !== 'GET') ? { 'Content-Length': Buffer.byteLength(body) } : {})
      }
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          resolve({ statusCode: res.statusCode, body: JSON.parse(data) });
        } catch (e) {
          resolve({ statusCode: res.statusCode, body: data });
        }
      });
    });

    req.setTimeout(1500, () => {
      req.destroy(new Error('Request timeout'));
    });

    req.on('error', (err) => reject(err));
    if (method !== 'GET') {
      req.write(body);
    }
    req.end();
  });
}

// Server Creation
const server = http.createServer(async (req, res) => {
  const start = Date.now();
  const parsedUrl = url.parse(req.url, true);
  const pathName = parsedUrl.pathname;
  
  // Trace context extraction & generation
  const incomingTraceId = req.headers['x-trace-id'];
  const incomingSpanId = req.headers['x-span-id'];

  const activeTraceId = incomingTraceId || crypto.randomBytes(16).toString('hex');
  const activeSpanId = crypto.randomBytes(8).toString('hex');

  // Handle body extraction
  let body = '';
  req.on('data', chunk => body += chunk);
  
  await new Promise(resolve => req.on('end', resolve));
  let jsonBody = {};
  if (body) {
    try { jsonBody = JSON.parse(body); } catch(e) {}
  }

  // Network Delay Simulation
  const delay = faultInjector.getDelay();
  if (delay > 0) {
    await new Promise(resolve => setTimeout(resolve, delay));
  }

  // Custom response logic wrapper
  const sendResponse = (statusCode, data, contentType = 'application/json') => {
    res.writeHead(statusCode, { 'Content-Type': contentType });
    res.end(typeof data === 'string' ? data : JSON.stringify(data));
    
    const duration = Date.now() - start;
    incMetric(req.method, pathName, statusCode);
    
    // Send trace span to Jaeger asynchronously
    sendSpan(`${req.method} ${pathName}`, activeTraceId, activeSpanId, incomingSpanId, start, duration, statusCode);
  };

  // Base metrics route
  if (pathName.endsWith('/metrics') && req.method === 'GET') {
    let output = '';
    output += '# HELP http_requests_total Total number of HTTP requests\n';
    output += '# TYPE http_requests_total counter\n';
    Object.entries(requestCounter).forEach(([labels, count]) => {
      output += `http_requests_total{${labels}} ${count}\n`;
    });
    
    output += '# HELP process_cpu_usage_ratio Process CPU usage ratio\n';
    output += '# TYPE process_cpu_usage_ratio gauge\n';
    output += `process_cpu_usage_ratio ${getCpuUsageRatio().toFixed(4)}\n`;
    
    output += '# HELP process_memory_usage_ratio Process memory usage ratio\n';
    output += '# TYPE process_memory_usage_ratio gauge\n';
    output += `process_memory_usage_ratio ${getMemoryUsageRatio().toFixed(4)}\n`;

    return sendResponse(200, output, 'text/plain; version=0.0.4');
  }

  // Fault Injection
  if (pathName.endsWith('/inject-fault') && req.method === 'POST') {
    const { type, duration_sec, config } = jsonBody;
    if (!type) {
      return sendResponse(400, { error: 'Missing fault type' });
    }
    const currentFault = faultInjector.getActiveFault();
    if (currentFault && currentFault.active) {
      return sendResponse(409, {
        error: 'Conflict: A fault is already active on this service',
        active_fault: currentFault
      });
    }
    faultInjector.inject(type, duration_sec || 60, config || {});
    return sendResponse(200, { message: 'Fault ' + type + ' injected successfully' });
  }

  // State Reset & Metrics Cleanup
  if (pathName.endsWith('/reset') && req.method === 'POST') {
    for (const key in requestCounter) {
      delete requestCounter[key];
    }
    faultInjector.reset();
    return sendResponse(200, { status: 'success', message: 'Service state cleanly reset' });
  }

  // Health checks
  if (pathName.endsWith('/fault-status') && req.method === 'GET') {
    return sendResponse(200, faultInjector.getActiveFault());
  }
  if (pathName.endsWith('/health') && req.method === 'GET') {
    return sendResponse(200, { status: 'UP', service: SERVICE_NAME });
  }
  if ((pathName === '/' || pathName.endsWith('/' + SERVICE_NAME)) && req.method === 'GET') {
    return sendResponse(200, SERVICE_NAME + ' is running');
  }

  // Inject tracer context for sub-calls
  const ctx = { traceId: activeTraceId, spanId: activeSpanId };

  // Business Logic router
  try {
    await routeRequest(pathName, req.method, jsonBody, ctx, sendResponse, parsedUrl.query);
  } catch (err) {
    console.error(err);
    sendResponse(500, { error: 'Internal Server Error', details: err.message });
  }
});


async function routeRequest(path, method, body, ctx, send, query) {
  if (path === '/api/payment/create-order' && method === 'POST') {
    // Return mock order details directly (zero external package dependencies)
    send(200, { id: 'pay_mock_' + Date.now(), amount: body.amount, currency: body.currency, status: 'created' });
  } else if (path === '/api/payment/verify-payment' && method === 'POST') {
    send(200, { status: 'success', message: 'Payment verified successfully' });
  } else {
    send(404, { error: 'Not Found' });
  }
}


server.listen(PORT, () => {
  console.log(SERVICE_NAME + ' listening at http://localhost:' + PORT);
});
