/**
 * Pyodide Loader
 *
 * Lazy-loads the Pyodide Python runtime for browser-based Python execution.
 * Uses the pyodide npm package which bundles all necessary files.
 *
 * In development: loads from node_modules/pyodide/
 * In production: loads from bundled /pyodide/ directory
 */

import type { PyodideStatus } from '../types/python-scripts'

// Pyodide is loaded dynamically at runtime (not statically imported)
// to avoid bundling issues — the bare "pyodide" specifier can't be
// resolved by the browser in production builds.
let loadPyodideModule: any = null

// Pyodide instance singleton
let pyodideInstance: any = null
let pyodidePromise: Promise<any> | null = null
let loadStatus: PyodideStatus = 'not_loaded'
let loadError: string | null = null

// Progress callback type
type ProgressCallback = (status: PyodideStatus, message: string, progress?: number) => void

/**
 * Get current Pyodide loading status
 */
export function getPyodideStatus(): { status: PyodideStatus; error: string | null } {
  return { status: loadStatus, error: loadError }
}

/**
 * Check if Pyodide is ready
 */
export function isPyodideReady(): boolean {
  return loadStatus === 'ready' && pyodideInstance !== null
}

/**
 * Get the Pyodide instance (throws if not ready)
 */
export function getPyodide(): any {
  if (!pyodideInstance) {
    throw new Error('Pyodide not loaded. Call loadPyodide() first.')
  }
  return pyodideInstance
}

/**
 * Load Pyodide runtime
 *
 * @param onProgress - Optional callback for loading progress
 * @returns Promise that resolves to Pyodide instance
 */
export async function loadPyodide(onProgress?: ProgressCallback): Promise<any> {
  // Return existing instance if already loaded
  if (pyodideInstance) {
    onProgress?.('ready', 'Pyodide already loaded')
    return pyodideInstance
  }

  // Return existing promise if loading in progress
  if (pyodidePromise) {
    return pyodidePromise
  }

  // Start loading
  loadStatus = 'loading'
  loadError = null
  onProgress?.('loading', 'Initializing Pyodide...', 0)

  pyodidePromise = (async () => {
    try {
      onProgress?.('loading', 'Loading Pyodide runtime...', 10)

      // Dynamically import pyodide — works in both dev (node_modules) and production (CDN fallback)
      if (!loadPyodideModule) {
        try {
          const mod = await import('pyodide')
          loadPyodideModule = mod.loadPyodide
        } catch {
          // Fallback: load from CDN via script tag
          const cdnUrl = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.mjs'
          const mod = await import(/* @vite-ignore */ cdnUrl)
          loadPyodideModule = mod.loadPyodide
        }
      }

      onProgress?.('loading', 'Initializing Python interpreter...', 30)

      // Initialize Pyodide using the dynamically loaded module
      const pyodide = await loadPyodideModule({
        stdout: (text: string) => {
          console.log('[Pyodide stdout]', text)
        },
        stderr: (text: string) => {
          console.error('[Pyodide stderr]', text)
        }
      })

      onProgress?.('loading', 'Loading NumPy...', 50)

      // Pre-load commonly used packages
      await pyodide.loadPackage(['numpy'])

      onProgress?.('loading', 'Loading SciPy...', 70)
      await pyodide.loadPackage(['scipy'])

      onProgress?.('loading', 'Setting up ICCSFlux bridge...', 90)

      // Set up the NISystem Python module
      await setupNISystemModule(pyodide)

      onProgress?.('ready', 'Pyodide ready', 100)

      pyodideInstance = pyodide
      loadStatus = 'ready'
      return pyodide

    } catch (error: any) {
      loadStatus = 'error'
      loadError = error.message || 'Failed to load Pyodide'
      onProgress?.('error', loadError ?? 'Unknown error')
      pyodidePromise = null
      throw error
    }
  })()

  return pyodidePromise
}

/**
 * Set up the NISystem Python module with bridge functions
 */
async function setupNISystemModule(pyodide: any): Promise<void> {
  // Create the nisystem module in Python
  const moduleCode = `
import sys
from types import ModuleType

# Create nisystem module
nisystem = ModuleType('nisystem')
sys.modules['nisystem'] = nisystem

# Placeholder classes - will be replaced with JS proxies at runtime
class _Tags:
    """Placeholder for channel access - replaced at runtime"""
    def __getattr__(self, name):
        return 0.0
    def __getitem__(self, name):
        return 0.0
    def keys(self):
        return []
    def get(self, name, default=0.0):
        return default

class _Session:
    """Placeholder for session state - replaced at runtime"""
    @property
    def active(self):
        return False
    @property
    def elapsed(self):
        return 0.0
    @property
    def recording(self):
        return False

    def start(self):
        """Start data acquisition"""
        pass

    def stop(self):
        """Stop data acquisition"""
        pass

    def start_recording(self, filename=None):
        """Start recording data to file"""
        pass

    def stop_recording(self):
        """Stop recording data"""
        pass

    @staticmethod
    def now():
        """Get current timestamp in milliseconds"""
        import time
        return int(time.time() * 1000)

    @staticmethod
    def now_iso():
        """Get current time as ISO 8601 string"""
        from datetime import datetime
        return datetime.now().isoformat()

    @staticmethod
    def time_of_day():
        """Get current time of day as HH:MM:SS"""
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

class _Outputs:
    """Placeholder for output control - replaced at runtime"""
    def set(self, channel, value):
        pass
    def __setitem__(self, name, value):
        self.set(name, value)

# Placeholder instances
tags = _Tags()
session = _Session()
outputs = _Outputs()

# Placeholder functions
def publish(name, value, units='', description=''):
    pass

async def next_scan():
    import asyncio
    await asyncio.sleep(0.1)

async def wait_for(seconds):
    import asyncio
    await asyncio.sleep(seconds)

async def wait_until(condition, timeout=0):
    import asyncio
    import time
    start = time.time()
    while True:
        try:
            if condition():
                return True
        except:
            pass
        if timeout > 0 and (time.time() - start) >= timeout:
            return False
        await asyncio.sleep(0.1)

# Unit conversion functions
def F_to_C(f):
    return (f - 32) * 5 / 9

def C_to_F(c):
    return c * 9 / 5 + 32

def GPM_to_LPM(gpm):
    return gpm * 3.78541

def LPM_to_GPM(lpm):
    return lpm * 0.264172

def PSI_to_bar(psi):
    return psi * 0.0689476

def bar_to_PSI(bar):
    return bar * 14.5038

def gal_to_L(gal):
    return gal * 3.78541

def L_to_gal(L):
    return L * 0.264172

def BTU_to_kJ(btu):
    return btu * 1.055

def kJ_to_BTU(kj):
    return kj * 0.9478

def lb_to_kg(lb):
    return lb * 0.453592

def kg_to_lb(kg):
    return kg * 2.20462

# Derived value helper classes
class RateCalculator:
    """Calculate rate of change over a time window"""
    def __init__(self, window_seconds=60):
        self._samples = []
        self._window = window_seconds

    def update(self, value, timestamp=None):
        import time
        if timestamp is None:
            timestamp = time.time()
        self._samples.append((timestamp, value))
        # Trim old samples
        cutoff = timestamp - self._window
        self._samples = [(t, v) for t, v in self._samples if t >= cutoff]
        # Calculate rate
        if len(self._samples) < 2:
            return 0.0
        dt = self._samples[-1][0] - self._samples[0][0]
        dv = self._samples[-1][1] - self._samples[0][1]
        return dv / dt if dt > 0 else 0.0

    def reset(self):
        self._samples = []

class Accumulator:
    """Accumulate incremental changes"""
    def __init__(self, initial=0):
        self._total = initial
        self._last_value = None

    def update(self, value):
        if self._last_value is not None:
            delta = value - self._last_value
            if delta > 0:
                self._total += delta
        self._last_value = value
        return self._total

    def reset(self):
        self._total = 0
        self._last_value = None

    @property
    def total(self):
        return self._total

class EdgeDetector:
    """Detect rising/falling edges"""
    def __init__(self, threshold=0.5):
        self._threshold = threshold
        self._last_state = None

    def update(self, value):
        state = value > self._threshold
        rising = False
        falling = False
        if self._last_state is not None:
            rising = state and not self._last_state
            falling = not state and self._last_state
        self._last_state = state
        return (rising, falling, state)

    def reset(self):
        self._last_state = None

class RollingStats:
    """Calculate rolling statistics over a sample window"""
    def __init__(self, window_size=100):
        self._window = window_size
        self._samples = []

    def update(self, value):
        self._samples.append(value)
        if len(self._samples) > self._window:
            self._samples.pop(0)

        n = len(self._samples)
        mean = sum(self._samples) / n
        variance = sum((x - mean) ** 2 for x in self._samples) / n
        return {
            'mean': mean,
            'min': min(self._samples),
            'max': max(self._samples),
            'std': variance ** 0.5,
            'count': n
        }

    def reset(self):
        self._samples = []

class Scheduler:
    """APScheduler-like job scheduler for ICCSFlux scripts"""

    def __init__(self):
        self._jobs = {}  # name -> job dict
        self._job_counter = 0

    def add_interval(self, name, seconds=None, minutes=None, hours=None, func=None):
        """Add a job that runs at fixed intervals"""
        import time

        # Calculate interval in seconds
        interval = 0
        if seconds: interval += seconds
        if minutes: interval += minutes * 60
        if hours: interval += hours * 3600

        if interval <= 0:
            raise ValueError("Interval must be positive")

        self._jobs[name] = {
            'type': 'interval',
            'func': func,
            'interval': interval,
            'next_run': time.time() + interval,
            'paused': False,
            'run_count': 0
        }
        return name

    def add_cron(self, name, hour=None, minute=None, second=0,
                 day_of_week=None, func=None):
        """Add a cron-like job that runs at specific times

        Args:
            hour: 0-23 (None = every hour)
            minute: 0-59 (None = every minute)
            second: 0-59
            day_of_week: 0-6 (Mon-Sun) or None for every day
            func: function to call
        """
        self._jobs[name] = {
            'type': 'cron',
            'func': func,
            'hour': hour,
            'minute': minute,
            'second': second,
            'day_of_week': day_of_week,
            'last_run_minute': None,  # Prevent running multiple times per minute
            'paused': False,
            'run_count': 0
        }
        return name

    def add_once(self, name, delay, func=None):
        """Add a one-shot job that runs once after delay seconds"""
        import time

        self._jobs[name] = {
            'type': 'once',
            'func': func,
            'run_at': time.time() + delay,
            'paused': False,
            'executed': False
        }
        return name

    def pause(self, name):
        """Pause a job"""
        if name in self._jobs:
            self._jobs[name]['paused'] = True

    def resume(self, name):
        """Resume a paused job"""
        if name in self._jobs:
            self._jobs[name]['paused'] = False

    def remove(self, name):
        """Remove a job"""
        if name in self._jobs:
            del self._jobs[name]

    def get_jobs(self):
        """Get list of all job names and their status"""
        return {name: {
            'type': job['type'],
            'paused': job['paused'],
            'run_count': job.get('run_count', 0)
        } for name, job in self._jobs.items()}

    def is_paused(self, name):
        """Check if a job is paused"""
        return self._jobs.get(name, {}).get('paused', False)

    async def tick(self):
        """Check and run any due jobs. Call this in your main loop."""
        import time
        from datetime import datetime

        now = time.time()
        dt_now = datetime.now()

        jobs_to_remove = []

        for name, job in self._jobs.items():
            if job['paused']:
                continue

            should_run = False

            if job['type'] == 'interval':
                if now >= job['next_run']:
                    should_run = True
                    job['next_run'] = now + job['interval']

            elif job['type'] == 'cron':
                # Check if current time matches cron spec
                matches = True

                if job['hour'] is not None and dt_now.hour != job['hour']:
                    matches = False
                if job['minute'] is not None and dt_now.minute != job['minute']:
                    matches = False
                if job['day_of_week'] is not None and dt_now.weekday() != job['day_of_week']:
                    matches = False

                # Prevent running multiple times in the same minute
                current_minute = (dt_now.hour, dt_now.minute)
                if matches and job['last_run_minute'] != current_minute:
                    should_run = True
                    job['last_run_minute'] = current_minute

            elif job['type'] == 'once':
                if not job['executed'] and now >= job['run_at']:
                    should_run = True
                    job['executed'] = True
                    jobs_to_remove.append(name)

            if should_run and job.get('func'):
                try:
                    result = job['func']()
                    # Handle async functions
                    if hasattr(result, '__await__'):
                        await result
                    job['run_count'] = job.get('run_count', 0) + 1
                except Exception as e:
                    print(f"Scheduler error in job '{name}': {e}")

        # Remove one-shot jobs that have executed
        for name in jobs_to_remove:
            del self._jobs[name]

# Time helper functions (module-level convenience)
def now():
    """Get current Unix timestamp in seconds (float)"""
    import time
    return time.time()

def now_ms():
    """Get current Unix timestamp in milliseconds (int)"""
    import time
    return int(time.time() * 1000)

def now_iso():
    """Get current time as ISO 8601 string"""
    from datetime import datetime
    return datetime.now().isoformat()

def time_of_day():
    """Get current time of day as HH:MM:SS string"""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")

def format_timestamp(ts_ms, fmt="%Y-%m-%d %H:%M:%S"):
    """Format a millisecond timestamp to a string"""
    from datetime import datetime
    return datetime.fromtimestamp(ts_ms / 1000).strftime(fmt)

def elapsed_since(start_ts):
    """Get elapsed time in seconds since start_ts (in seconds)"""
    import time
    return time.time() - start_ts

# Expose in nisystem module
nisystem.tags = tags
nisystem.session = session
nisystem.outputs = outputs
nisystem.publish = publish
nisystem.next_scan = next_scan
nisystem.wait_for = wait_for
nisystem.wait_until = wait_until

# Time functions
nisystem.now = now
nisystem.now_ms = now_ms
nisystem.now_iso = now_iso
nisystem.time_of_day = time_of_day
nisystem.format_timestamp = format_timestamp
nisystem.elapsed_since = elapsed_since

# Conversions
nisystem.F_to_C = F_to_C
nisystem.C_to_F = C_to_F
nisystem.GPM_to_LPM = GPM_to_LPM
nisystem.LPM_to_GPM = LPM_to_GPM
nisystem.PSI_to_bar = PSI_to_bar
nisystem.bar_to_PSI = bar_to_PSI
nisystem.gal_to_L = gal_to_L
nisystem.L_to_gal = L_to_gal
nisystem.BTU_to_kJ = BTU_to_kJ
nisystem.kJ_to_BTU = kJ_to_BTU
nisystem.lb_to_kg = lb_to_kg
nisystem.kg_to_lb = kg_to_lb

# Helpers
nisystem.RateCalculator = RateCalculator
nisystem.Accumulator = Accumulator
nisystem.EdgeDetector = EdgeDetector
nisystem.RollingStats = RollingStats
nisystem.Scheduler = Scheduler

print("ICCSFlux Python module initialized (NumPy + SciPy + Scheduler loaded)")
`

  await pyodide.runPythonAsync(moduleCode)
}

/**
 * Reset Pyodide (for testing/debugging)
 */
export function resetPyodide(): void {
  pyodideInstance = null
  pyodidePromise = null
  loadStatus = 'not_loaded'
  loadError = null
}
