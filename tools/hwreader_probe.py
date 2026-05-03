#!/usr/bin/env python3
"""
hwreader_probe.py — direct HardwareReader exerciser against real cDAQ hardware.

Builds an NISystemConfig in code (no INI files, no project loader, no MQTT,
no daq_service) and instantiates HardwareReader pointed at the cDAQ-9188
named "MikeAndMike". Watches the reader's internal state once a second and
flags stalls.

It answers exactly one question: does the reader hang or silently stall when
pointed at the real chassis? If yes, it tells you which task / channel /
thread is responsible.

  - Per-channel stall detection (value_timestamps not advancing)
  - Per-task health (alive flag, consecutive_errors, total_errors, max_lag)
  - Reader-thread death (reader_died flag from get_health_status)
  - Whole-process wedge: faulthandler is registered on Ctrl-Break (Windows)
    or SIGUSR1 (Unix) so you can dump every thread's stack even if the
    process is jammed inside a DAQmx call.

Edit CHANNELS / SAMPLE_RATE_HZ below to change what's probed. No CLI flags
on purpose — this is an instrument, not a product.

Run:    python tools/hwreader_probe.py
Stop:   Ctrl-C
Probe:  Ctrl-Break  (force stack dump while running, even if wedged)
"""

import faulthandler
import logging
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "daq_service"))

from config_parser import (
    NISystemConfig, SystemConfig, DataViewerConfig, ChassisConfig,
    ModuleConfig, ChannelConfig, ChannelType,
)
from hardware_reader import HardwareReader


# === EDIT THIS BLOCK =====================================================
SAMPLE_RATE_HZ = 10.0
CHASSIS_DEVICE = "MikeAndMike"  # NI MAX name of the cDAQ-9188
MAX_DURATION_S = 12.0           # auto-exit after this many seconds (0 = run forever)
TEST_OUTPUT_VALUE_MA = 5.0      # write this to each output, verify read-back, reset to 0

# Full hardware complement: every AI on every input module + every AO on every
# output module. Same call paths the daq_service exercises in production.
#   Mod1 = NI 9208      (16-ch current input,  ai0..ai15)
#   Mod2 = NI 9266      ( 8-ch current output, ao0..ao7)
#   Mod3 = NI 9266      ( 8-ch current output, ao0..ao7)
#   Mod4 = NI 9207      ( 8-V + 8-mA input,    ai0..ai7 voltage, ai8..ai15 current)
# (channel_name, physical_channel, channel_type, units)
CHANNELS = (
    [(f"Mod1_ai{i:02d}_mA", f"{CHASSIS_DEVICE}Mod1/ai{i}",
      ChannelType.CURRENT_INPUT, "mA") for i in range(16)] +
    [(f"Mod4_ai{i:02d}_V",  f"{CHASSIS_DEVICE}Mod4/ai{i}",
      ChannelType.VOLTAGE_INPUT, "V") for i in range(8)] +
    [(f"Mod4_ai{i:02d}_mA", f"{CHASSIS_DEVICE}Mod4/ai{i}",
      ChannelType.CURRENT_INPUT, "mA") for i in range(8, 16)] +
    [(f"Mod2_ao{i:02d}_mA", f"{CHASSIS_DEVICE}Mod2/ao{i}",
      ChannelType.CURRENT_OUTPUT, "mA") for i in range(8)] +
    [(f"Mod3_ao{i:02d}_mA", f"{CHASSIS_DEVICE}Mod3/ao{i}",
      ChannelType.CURRENT_OUTPUT, "mA") for i in range(8)]
)
# =========================================================================

STALL_FACTOR = 3.0          # channel is "stalled" if age > this many scan periods
STATUS_INTERVAL_S = 1.0
CLOSE_TIMEOUT_S = 10.0
STACK_DUMP_EVERY_N_STALL_TICKS = 5


def build_config() -> NISystemConfig:
    sysconf = SystemConfig(scan_rate_hz=SAMPLE_RATE_HZ, simulation_mode=False)
    chassis = ChassisConfig(
        name=CHASSIS_DEVICE,
        chassis_type="cDAQ-9188",
        device_name=CHASSIS_DEVICE,
    )
    modules = {
        f"{CHASSIS_DEVICE}Mod1": ModuleConfig(
            name=f"{CHASSIS_DEVICE}Mod1", module_type="NI 9208",
            chassis=CHASSIS_DEVICE, slot=1),
        f"{CHASSIS_DEVICE}Mod2": ModuleConfig(
            name=f"{CHASSIS_DEVICE}Mod2", module_type="NI 9266",
            chassis=CHASSIS_DEVICE, slot=2),
        f"{CHASSIS_DEVICE}Mod3": ModuleConfig(
            name=f"{CHASSIS_DEVICE}Mod3", module_type="NI 9266",
            chassis=CHASSIS_DEVICE, slot=3),
        f"{CHASSIS_DEVICE}Mod4": ModuleConfig(
            name=f"{CHASSIS_DEVICE}Mod4", module_type="NI 9207",
            chassis=CHASSIS_DEVICE, slot=4),
    }
    channels = {}
    for name, phys, ctype, units in CHANNELS:
        channels[name] = ChannelConfig(
            name=name,
            physical_channel=phys,
            channel_type=ctype,
            units=units,
            terminal_config="differential",
        )
    return NISystemConfig(
        system=sysconf,
        dataviewer=DataViewerConfig(),
        chassis={CHASSIS_DEVICE: chassis},
        modules=modules,
        channels=channels,
        safety_actions={},
    )


def dump_all_stacks(label: str) -> None:
    print(f"\n----- STACKS [{label}] @ {time.strftime('%H:%M:%S')} -----",
          flush=True)
    name_by_tid = {t.ident: t.name for t in threading.enumerate()}
    for tid, frame in sys._current_frames().items():
        print(f"\n  Thread {tid} ({name_by_tid.get(tid, '?')}):")
        print("".join("    " + ln for ln in traceback.format_stack(frame)))
    print("----- END STACKS -----\n", flush=True)


def daqmx_smoke_test() -> bool:
    """Phase-0: direct DAQmx call that mirrors _create_combined_analog_task.

    HardwareReader's task-creation paths log errors via logger.error(str(e))
    which loses the traceback and the DAQmx error code. By replicating the
    same call sequence here directly, we surface the exact step that the
    driver rejects.

    Returns True if the smoke test passes; False otherwise. Either way, the
    probe still proceeds to the full HardwareReader phase so we can compare.
    """
    import numpy as np
    import nidaqmx
    from nidaqmx.constants import (
        TerminalConfiguration, AcquisitionType, ADCTimingMode,
        OverwriteMode, CurrentShuntResistorLocation,
    )
    from nidaqmx.stream_readers import AnalogMultiChannelReader

    print("\n--- PHASE 0: direct DAQmx smoke test on MikeAndMikeMod1/ai0 ---")

    def fmt_daq_err(e: Exception) -> str:
        code = getattr(e, "error_code", None)
        return f"{type(e).__name__}: {e}" + (f"  [code={code}]" if code else "")

    # Variants to find which arg combination the 9208 actually accepts.
    # First success wins; remaining variants are skipped.
    variants = [
        ("min=0,    max=0.020,  DIFF, internal_shunt", dict(
            terminal_config=TerminalConfiguration.DIFF,
            min_val=0.0, max_val=0.020,
            shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL)),
        ("min=-.02, max=0.020,  DIFF, internal_shunt", dict(
            terminal_config=TerminalConfiguration.DIFF,
            min_val=-0.020, max_val=0.020,
            shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL)),
        ("min=0,    max=0.020,  DIFF, NO shunt kwarg", dict(
            terminal_config=TerminalConfiguration.DIFF,
            min_val=0.0, max_val=0.020)),
        ("min=-.02, max=0.020,  DIFF, NO shunt kwarg", dict(
            terminal_config=TerminalConfiguration.DIFF,
            min_val=-0.020, max_val=0.020)),
        ("min=0,    max=0.020,  NO terminal, NO shunt", dict(
            min_val=0.0, max_val=0.020)),
        ("min=-.02, max=0.020,  NO terminal, NO shunt", dict(
            min_val=-0.020, max_val=0.020)),
    ]

    winner = None
    for label, kwargs in variants:
        task_name = f"smoke_{abs(hash(label)) & 0xFFFF:04x}"
        try:
            with nidaqmx.Task(task_name) as t:
                t.ai_channels.add_ai_current_chan("MikeAndMikeMod1/ai0", **kwargs)
                print(f"  OK  add_ai_current_chan {label}")
                winner = (label, kwargs)
                break
        except Exception as e:
            print(f"  FAIL add_ai_current_chan {label}: {fmt_daq_err(e)}")

    if winner is None:
        print("--- smoke test FAILED — no variant accepted by driver ---")
        print("--- check NI MAX device self-test for MikeAndMikeMod1 ---\n")
        return False

    print(f"\n  >>> WINNING ARGS: {winner[0]}")

    def step(label, fn):
        try:
            result = fn()
            print(f"  OK  {label}")
            return result
        except Exception as e:
            print(f"  FAIL {label}: {fmt_daq_err(e)}")
            traceback.print_exc()
            raise

    try:
        with nidaqmx.Task("smoke_full") as task:
            ai = step(f"add_ai_current_chan ({winner[0]})",
                      lambda: task.ai_channels.add_ai_current_chan(
                          "MikeAndMikeMod1/ai0", **winner[1]))
            try:
                step("ai_adc_timing_mode = HIGH_SPEED",
                     lambda: setattr(ai, "ai_adc_timing_mode",
                                     ADCTimingMode.HIGH_SPEED))
            except Exception:
                pass  # non-fatal; continue to see what else breaks
            step(
                f"cfg_samp_clk_timing(rate={SAMPLE_RATE_HZ}, CONTINUOUS, samps=1000)",
                lambda: task.timing.cfg_samp_clk_timing(
                    rate=SAMPLE_RATE_HZ,
                    sample_mode=AcquisitionType.CONTINUOUS,
                    samps_per_chan=1000,
                ),
            )
            step("in_stream.over_write = OVERWRITE_UNREAD_SAMPLES",
                 lambda: setattr(task.in_stream, "over_write",
                                 OverwriteMode.OVERWRITE_UNREAD_SAMPLES))
            step("task.start()", task.start)
            time.sleep(0.5)
            rdr = AnalogMultiChannelReader(task.in_stream)
            buf = np.zeros((1, 5), dtype=np.float64)
            step("read 5 samples (timeout=2s)",
                 lambda: rdr.read_many_sample(
                     buf, number_of_samples_per_channel=5, timeout=2.0))
            print(f"  samples: {buf.flatten()}")
            step("task.stop()", task.stop)
    except Exception:
        print("--- smoke test FAILED — see step above for the offending call ---\n")
        return False

    # Phase 0b: AO smoke on the 9266. Drives 0 mA only — no field-side movement.
    print("\n--- PHASE 0b: AO smoke test on MikeAndMikeMod2/ao0 (writes 0 mA) ---")
    try:
        with nidaqmx.Task("smoke_ao") as t:
            t.ao_channels.add_ao_current_chan(
                f"{CHASSIS_DEVICE}Mod2/ao0", min_val=0.0, max_val=0.020)
            print("  OK  add_ao_current_chan(min=0, max=0.020)")
            t.start()
            print("  OK  task.start()")
            t.write(0.0)  # 0 A
            print("  OK  task.write(0.0 A)")
            rb = t.read()
            print(f"  OK  task.read() readback = {rb*1000:.4f} mA")
            t.stop()
            print("  OK  task.stop()")
    except Exception as e:
        print(f"  FAIL AO smoke: {fmt_daq_err(e)}")
        traceback.print_exc()
        print("--- AO smoke FAILED ---\n")
        return False

    print("--- smoke test PASSED ---\n")
    return True


def exercise_outputs(reader, test_value_ma: float) -> dict:
    """Phase 1.5: write `test_value_ma` to every CURRENT_OUTPUT, verify
    read-back via the cached output_values (HardwareReader.write_channel
    populates this from a real task.read() inside the call), reset to 0.

    Returns {channel_name: (write_ok, readback_ma, delta_ma)}.
    """
    print(f"\n--- PHASE 1.5: write {test_value_ma} mA to every output, verify, reset ---")
    out_channels = [c for c in CHANNELS if c[2] == ChannelType.CURRENT_OUTPUT]
    results = {}
    fails = 0
    for cname, _phys, _ct, _u in out_channels:
        ok = reader.write_channel(cname, test_value_ma)
        time.sleep(0.02)  # let the DAC + readback path settle
        rb = reader.output_values.get(cname)
        if rb is None:
            delta = float("inf")
        else:
            delta = abs(rb - test_value_ma)
        passed = ok and delta < 0.1
        results[cname] = (ok, rb, delta)
        marker = "OK  " if passed else "FAIL"
        if not passed:
            fails += 1
        print(f"  {marker} {cname:14s} write={ok!s:5}  readback="
              f"{rb if rb is not None else 'None'}  delta={delta:.4f} mA")
    # Reset all to 0 — leaves field side at the same state we started in.
    for cname, _phys, _ct, _u in out_channels:
        reader.write_channel(cname, 0.0)
    print(f"  reset {len(out_channels)} outputs to 0 mA")
    print(f"--- output exercise: {len(out_channels)-fails}/{len(out_channels)} passed ---\n")
    return results


def fmt_value(v) -> str:
    if v is None:
        return f"{'None':>10}"
    if isinstance(v, float):
        if v != v:  # NaN
            return f"{'NaN':>10}"
        return f"{v:10.4f}"
    return f"{str(v):>10}"


def main() -> int:
    # Surface the daq_service module's log output. Without this, errors raised
    # inside _create_combined_analog_task (and friends) are swallowed silently
    # because the root logger has no handler in this standalone harness.
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    faulthandler.enable()  # Crash signals (SIGSEGV/SIGFPE/etc.); works on Win+Unix.

    # User-triggered live stack dump. faulthandler.register() is Unix-only on
    # this Python build, so install a regular signal handler that calls our
    # own dump_all_stacks. DAQmx releases the GIL inside blocking reads, so
    # this still fires even if the reader thread looks wedged.
    def _on_dump_signal(_sig, _frame):
        dump_all_stacks("user-signal")
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_dump_signal)
    elif hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, _on_dump_signal)

    print(f"hwreader_probe — {len(CHANNELS)} channels @ {SAMPLE_RATE_HZ} Hz "
          f"on {CHASSIS_DEVICE}")
    print("Press Ctrl-Break (Windows) / SIGUSR1 (Unix) for a live stack dump.")
    print("Press Ctrl-C to stop.\n")

    daqmx_smoke_test()

    config = build_config()

    print("Instantiating HardwareReader (opens DAQmx tasks)...")
    init_t0 = time.monotonic()
    try:
        reader = HardwareReader(config)
    except Exception as e:
        elapsed = time.monotonic() - init_t0
        print(f"FATAL: HardwareReader init failed after {elapsed:.2f}s: {e}",
              file=sys.stderr)
        traceback.print_exc()
        return 2
    print(f"Reader started in {time.monotonic() - init_t0:.2f}s.\n")

    output_results = exercise_outputs(reader, TEST_OUTPUT_VALUE_MA)

    stop_evt = threading.Event()
    def on_sigint(_sig, _frame):
        if stop_evt.is_set():
            print("\nSecond Ctrl-C — forcing exit.")
            sys.exit(130)
        print("\nCtrl-C — stopping after this tick...")
        stop_evt.set()
    signal.signal(signal.SIGINT, on_sigint)

    in_channels = [c for c in CHANNELS if c[2] != ChannelType.CURRENT_OUTPUT]
    out_channels = [c for c in CHANNELS if c[2] == ChannelType.CURRENT_OUTPUT]

    period = 1.0 / SAMPLE_RATE_HZ
    stall_age = STALL_FACTOR * period
    consecutive_stall_ticks = 0
    iter_n = 0
    deadline = (time.monotonic() + MAX_DURATION_S) if MAX_DURATION_S > 0 else None

    try:
        while not stop_evt.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                print(f"[duration cap {MAX_DURATION_S}s reached — stopping]")
                break
            iter_n += 1
            tick_start = time.monotonic()
            wall_now = time.time()

            health = reader.get_health_status()
            values = reader.read_all()
            ts_map = dict(reader.value_timestamps)

            stalled = []
            for cname, _p, ctype, _u in in_channels:
                ts = ts_map.get(cname)
                age = (wall_now - ts) if ts else None
                if age is None or age > stall_age:
                    stalled.append((cname, age))

            tag = "ALERT" if (stalled or health["reader_died"]
                              or not health["healthy"]) else "OK"
            print(f"[{iter_n:04d} {tag}] "
                  f"running={health['running']} "
                  f"died={health['reader_died']} "
                  f"healthy={health['healthy']} "
                  f"recov={health['recovery_attempts']} "
                  f"consumer={health['consumer_alive']} "
                  f"slowpoll={health['slow_poll_alive']} "
                  f"tasks={health['task_count']} "
                  f"in_fresh={len(in_channels)-len(stalled)}/{len(in_channels)}")

            for tname, ts in health.get("tasks", {}).items():
                last = ts.get("last_read_ts")
                last_s = (f"{(wall_now-last)*1000:.0f}ms ago"
                          if last else "never")
                print(f"        task[{tname}] alive={ts['alive']} "
                      f"reads={ts['reads']} cerr={ts['consecutive_errors']} "
                      f"terr={ts['total_errors']} "
                      f"lost={ts['samples_lost_queue_full']} "
                      f"max_lag={ts['max_lag']} last_read={last_s}")

            # Compact per-channel display: only on first tick, every 5th tick,
            # or when something is stale. 48 lines/tick at 10Hz buries the log.
            show_full = (iter_n == 1 or iter_n % 5 == 0 or stalled)
            if show_full:
                for cname, _phys, _ct, units in in_channels:
                    v = values.get(cname)
                    ts = ts_map.get(cname)
                    age = (wall_now - ts) if ts else None
                    age_s = f"{age*1000:5.0f}ms" if age is not None else " never"
                    flag = "STALE" if (age is None or age > stall_age) else "  ok"
                    print(f"        {flag} {cname:14s} {fmt_value(v)} {units:2s} {age_s}")
                for cname, _phys, _ct, units in out_channels:
                    v = values.get(cname)
                    print(f"         out {cname:14s} {fmt_value(v)} {units:2s} (commanded)")

            if stalled:
                consecutive_stall_ticks += 1
                print(f"  STALLED ({consecutive_stall_ticks}t): "
                      f"{[s[0] for s in stalled]}")
                if consecutive_stall_ticks % STACK_DUMP_EVERY_N_STALL_TICKS == 0:
                    dump_all_stacks(f"stall-tick-{consecutive_stall_ticks}")
            else:
                consecutive_stall_ticks = 0

            if health["reader_died"]:
                print("  READER DIED — dumping stacks and exiting.")
                dump_all_stacks("reader-died")
                stop_evt.set()
                break

            elapsed = time.monotonic() - tick_start
            remaining = STATUS_INTERVAL_S - elapsed
            if remaining > 0:
                stop_evt.wait(remaining)
    finally:
        # End-of-run summary
        try:
            final_values = reader.read_all()
            final_ts = dict(reader.value_timestamps)
            wall_now = time.time()
            print("\n=========== FINAL SUMMARY ===========")
            print(f"Ticks observed: {iter_n}")
            print(f"Output write/readback: "
                  f"{sum(1 for _,r in output_results.items() if r[0] and r[2]<0.1)}/"
                  f"{len(output_results)} passed")
            health = reader.get_health_status()
            for tname, ts in health.get("tasks", {}).items():
                print(f"  task[{tname}]: reads={ts['reads']} terr={ts['total_errors']} "
                      f"recov={ts['recovery_attempts']} lost={ts['samples_lost_queue_full']}")
            print("\nFinal channel values:")
            for cname, _phys, ctype, units in CHANNELS:
                v = final_values.get(cname)
                if ctype == ChannelType.CURRENT_OUTPUT:
                    tag = "ao "
                    age_s = "       "
                else:
                    ts = final_ts.get(cname)
                    age = (wall_now - ts) if ts else None
                    age_s = f"{age*1000:5.0f}ms" if age is not None else " never"
                    tag = "ai "
                print(f"  {tag} {cname:14s} {fmt_value(v)} {units:2s} {age_s}")
            print("=====================================\n")
        except Exception as e:
            print(f"summary failed: {e}")

        print("\nClosing reader...")
        close_done = threading.Event()
        close_err = []
        def _close():
            try:
                reader.close()
            except Exception as e:
                close_err.append(e)
            finally:
                close_done.set()
        threading.Thread(target=_close, daemon=True, name="closer").start()
        close_t0 = time.monotonic()
        if not close_done.wait(timeout=CLOSE_TIMEOUT_S):
            print(f"WARNING: close() did not return within {CLOSE_TIMEOUT_S:.1f}s "
                  f"— DAQmx is wedged. Dumping stacks.")
            dump_all_stacks("close-hang")
            print("Force-exiting; NI-DAQmx tasks may remain reserved until "
                  "the next process restart or NI MAX 'Self-Test'.")
            return 3
        if close_err:
            print(f"close() raised: {close_err[0]}")
            return 4
        print(f"Closed cleanly in {time.monotonic() - close_t0:.2f}s.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
