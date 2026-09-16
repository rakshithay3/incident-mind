let cpuInterval = null;
let memoryBuffer = [];
let memoryInterval = null;
let delayMs = 0;

const fs = require('fs');
const FAULT_STATE_FILE = '/tmp/pod_crash_state.json';

(function resumeCrashLoopIfNeeded() {
  try {
    if (fs.existsSync(FAULT_STATE_FILE)) {
      const state = JSON.parse(fs.readFileSync(FAULT_STATE_FILE, 'utf8'));
      const elapsedSec = (Date.now() - state.startedAt) / 1000;
      if (elapsedSec < state.durationSec) {
        console.warn('Resuming pod_crash loop, ' + (state.durationSec - elapsedSec).toFixed(1) + 's remaining');
        setTimeout(function() { process.exit(1); }, 500);
      } else {
        fs.unlinkSync(FAULT_STATE_FILE);
      }
    }
  } catch (e) {
    console.error('Failed to resume crash state', e);
  }
})();

const SERVICE_NAME = process.env.SERVICE_NAME || 'notification-service';
let activeFault = {
  active: false,
  fault_type: "",
  target_service: SERVICE_NAME,
  injected_at: "",
  scheduled_duration_sec: 0,
  auto_rollback: true
};

module.exports = {
  delayMiddleware: (req, res, next) => {
    if (delayMs > 0) {
      setTimeout(next, delayMs);
    } else {
      next();
    }
  },

  inject: (type, durationSec, config = {}) => {
    console.log('Injecting fault: ' + type + ' for ' + durationSec + 's');

    const rollback = () => {
      console.log('Rolling back fault: ' + type);
      if (cpuInterval) {
        clearInterval(cpuInterval);
        cpuInterval = null;
      }
      if (memoryInterval) {
        clearInterval(memoryInterval);
        memoryInterval = null;
        memoryBuffer = [];
        if (global.gc) {
          global.gc();
        }
      }
      if (fs.existsSync(FAULT_STATE_FILE)) fs.unlinkSync(FAULT_STATE_FILE);
      delayMs = 0;
      activeFault = {
        active: false,
        fault_type: "",
        target_service: SERVICE_NAME,
        injected_at: "",
        scheduled_duration_sec: 0,
        auto_rollback: true
      };
    };

    activeFault = {
      active: true,
      fault_type: type,
      target_service: SERVICE_NAME,
      injected_at: new Date().toISOString(),
      scheduled_duration_sec: durationSec,
      auto_rollback: durationSec > 0
    };

    if (durationSec > 0) {
      setTimeout(rollback, durationSec * 1000);
    }

    switch (type) {
      case 'cpu_stress':
        if (cpuInterval) clearInterval(cpuInterval);
        cpuInterval = setInterval(() => {
          const start = Date.now();
          while (Date.now() - start < 80) {
            Math.random() * Math.random();
          }
        }, 100);
        break;

      case 'memory_pressure':
        if (memoryInterval) clearInterval(memoryInterval);
        memoryBuffer = [];
        const MAX_BUFFERS = 12;
        memoryInterval = setInterval(() => {
          try {
            if (memoryBuffer.length < MAX_BUFFERS) {
              memoryBuffer.push(Buffer.alloc(20 * 1024 * 1024, 'x'));
            }
          } catch (e) {
            console.error('Memory allocation failed', e);
            clearInterval(memoryInterval);
          }
        }, 200);
        break;

      case 'network_delay':
        delayMs = config.delayMs || 2000;
        break;

      case 'pod_crash':
        console.warn('Pod crashing! Exiting process...');
        fs.writeFileSync(FAULT_STATE_FILE, JSON.stringify({
          startedAt: Date.now(),
          durationSec: durationSec
        }));
        setTimeout(function() {
          process.exit(1);
        }, 500);
        break;

      default:
        console.error('Unknown fault type: ' + type);
    }
  },

  getDelay: () => delayMs,
  getActiveFault: () => activeFault,
  reset: () => {
    if (cpuInterval) {
      clearInterval(cpuInterval);
      cpuInterval = null;
    }
    if (memoryInterval) {
      clearInterval(memoryInterval);
      memoryInterval = null;
      memoryBuffer = [];
      if (global.gc) {
        global.gc();
      }
    }
    if (fs.existsSync(FAULT_STATE_FILE)) fs.unlinkSync(FAULT_STATE_FILE);
    delayMs = 0;
    activeFault = {
      active: false,
      fault_type: "",
      target_service: SERVICE_NAME,
      injected_at: "",
      scheduled_duration_sec: 0,
      auto_rollback: true
    };
    console.log('Fault state cleanly reset.');
  }
};
