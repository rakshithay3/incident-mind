
const http = require('http');
const url = require('url');
const crypto = require('crypto');
const faultInjector = require('./fault-injector');

const PORT = process.env.PORT || 3007;
const SERVICE_NAME = process.env.SERVICE_NAME || 'search-service';

// Simple metric state
const requestCounter = {};
const durationBuckets = {};

function incMetric(method, route, code) {
  const key = `method="${method}",route="${route}",status_code="${code}"`;
  requestCounter[key] = (requestCounter[key] || 0) + 1;
}

// Generate traces to Jaeger (OTLP JSON)
function sendSpan(name, traceId, spanId, parentSpanId, startTime, durationMs) {
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
          status: { code: 1 }
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
    sendSpan(`${req.method} ${pathName}`, activeTraceId, activeSpanId, incomingSpanId, start, duration);
  };

  // Base metrics route
  if (pathName.endsWith('/metrics') && req.method === 'GET') {
    let output = '';
    output += '# HELP http_requests_total Total number of HTTP requests\n';
    output += '# TYPE http_requests_total counter\n';
    Object.entries(requestCounter).forEach(([labels, count]) => {
      output += `http_requests_total{${labels}} ${count}\n`;
    });
    return sendResponse(200, output, 'text/plain; version=0.0.4');
  }

  // Fault Injection
  if (pathName.endsWith('/inject-fault') && req.method === 'POST') {
    const { type, duration_sec, config } = jsonBody;
    if (!type) {
      return sendResponse(400, { error: 'Missing fault type' });
    }
    faultInjector.inject(type, duration_sec || 60, config || {});
    return sendResponse(200, { message: 'Fault ' + type + ' injected successfully' });
  }

  // Health checks
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


const products = [
  { id: 'p1', name: 'Keychron K2 Mechanical Keyboard', price: 7999 },
  { id: 'p2', name: 'Logitech MX Master 3S Mouse', price: 10999 },
  { id: 'p3', name: 'Sony WH-1000XM5 Headphones', price: 29999 },
  { id: 'p4', name: 'Elgato Stream Deck MK.2', price: 14999 },
  { id: 'p5', name: 'Philips Hue Smart Lightstrip', price: 4499 },
  { id: 'p6', name: 'Belkin 3-in-1 Wireless Charger', price: 11999 },
  { id: 'p7', name: 'Apple iPad Air M1', price: 54900 },
  { id: 'p8', name: 'Dell UltraSharp 27 Inch 4K Monitor', price: 38999 },
  { id: 'p9', name: 'Anker 737 Power Bank 140W', price: 12999 },
  { id: 'p10', name: 'SteelSeries Apex Pro Keyboard', price: 18999 },
  { id: 'p11', name: 'Razer DeathAdder V3 Pro Mouse', price: 13999 },
  { id: 'p12', name: 'Bose QuietComfort Ultra Earbuds', price: 25999 },
  { id: 'p13', name: 'Shure SM7B Cardioid Microphone', price: 36999 },
  { id: 'p14', name: 'ASUS ROG Swift 360Hz Monitor', price: 64999 },
  { id: 'p15', name: 'Peak Design Everyday Backpack', price: 21999 },
  { id: 'p16', name: 'Herman Miller Aeron Chair', price: 135000 }
];
async function routeRequest(path, method, body, ctx, send, query) {
  if (path === '/api/search' && method === 'GET') {
    const q = (query.q || '').toLowerCase();
    const results = products.filter(p => p.name.toLowerCase().includes(q));
    send(200, results);
  } else {
    send(404, { error: 'Not Found' });
  }
}


server.listen(PORT, () => {
  console.log(SERVICE_NAME + ' listening at http://localhost:' + PORT);
});
