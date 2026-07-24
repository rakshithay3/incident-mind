let cpuInterval = null;
let memoryBuffer = [];
let memoryInterval = null;
let delayMs = 0;

const SERVICE_NAME = process.env.SERVICE_NAME || 'auth-service';
let activeFault = {
  active: false,
  fault_type: "",
  target_service: SERVICE_NAME,
  injected_at: "",
  scheduled_duration_sec: 0,
  auto_rollback: true
};

module.exports = {
  // Middleware to inject network delay
  delayMiddleware: (req, res, next) => {
    if (delayMs > 0) {
      setTimeout(next, delayMs);
    } else {
      next();
    }
  },

  // Inject a fault
  inject: (type, durationSec, config = {}) => {
    console.log(`Injecting fault: ${type} for ${durationSec}s`);
    
    // Automatic Rollback Schedule
    const rollback = () => {
      console.log(`Rolling back fault: ${type}`);
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
        // Spin CPU in chunks to keep event loop somewhat responsive but high usage
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
        memoryInterval = setInterval(() => {
          try {
            // Allocate ~20MB buffers
            memoryBuffer.push(Buffer.alloc(20 * 1024 * 1024, 'x'));
          } catch (e) {
            console.error('Memory limit reached or allocation failed', e);
            clearInterval(memoryInterval);
          }
        }, 200);
        break;

      case 'network_delay':
        delayMs = config.delayMs || 2000; // default 2 seconds delay
        break;

      case 'pod_crash':
        console.warn('Pod crashing! Exiting process...');
        setTimeout(() => {
          process.exit(1);
        }, 500);
        break;

      default:
        console.error(`Unknown fault type: ${type}`);
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
    delayMs = 0;
    activeFault = {
      active: false,
      fault_type: "",
      target_service: SERVICE_NAME,
      injected_at: "",
      scheduled_duration_sec: 0,
      auto_rollback: true
    };
    console.log(`Fault state cleanly reset.`);
  }
};
