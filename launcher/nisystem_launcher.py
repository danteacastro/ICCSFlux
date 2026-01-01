"""
NISystem Launcher
A single executable to start/stop/manage the NISystem services on Windows.
Compile with: pyinstaller --onefile --windowed --icon=icon.ico nisystem_launcher.py
"""

import sys
import os
import subprocess
import time
import json
import threading
import signal
from pathlib import Path

# Try to import tkinter for GUI
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

# Configuration
APP_NAME = "NISystem"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883


def get_project_root():
    """Get the project root directory"""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        exe_dir = Path(sys.executable).parent
        # Check if we're in a subdirectory
        if (exe_dir.parent / "config" / "system.ini").exists():
            return exe_dir.parent
        elif (exe_dir / "config" / "system.ini").exists():
            return exe_dir
        else:
            # Look up the tree
            for parent in exe_dir.parents:
                if (parent / "config" / "system.ini").exists():
                    return parent
            return exe_dir
    else:
        # Running as script
        return Path(__file__).parent.parent


def get_python_exe():
    """Get the Python executable path"""
    root = get_project_root()

    # Check for venv
    if sys.platform == 'win32':
        venv_python = root / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / "venv" / "bin" / "python"

    if venv_python.exists():
        return str(venv_python)

    # Fall back to system Python
    return sys.executable


def get_config_path():
    """Get the config file path"""
    return get_project_root() / "config" / "system.ini"


def get_daq_service_path():
    """Get the DAQ service script path"""
    return get_project_root() / "services" / "daq_service" / "daq_service.py"


def get_pid_file():
    """Get the PID file path"""
    if sys.platform == 'win32':
        return Path(os.environ.get('TEMP', '.')) / "nisystem-daq.pid"
    else:
        return Path("/tmp/nisystem-daq.pid")


def get_log_file():
    """Get the log file path"""
    if sys.platform == 'win32':
        return Path(os.environ.get('TEMP', '.')) / "nisystem-daq.log"
    else:
        return Path("/tmp/nisystem-daq.log")


class NISystemService:
    """Manages the NISystem DAQ service"""

    def __init__(self):
        self.process = None
        self.pid = None

    def is_running(self):
        """Check if the service is running"""
        pid_file = get_pid_file()

        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                # Check if process exists
                if sys.platform == 'win32':
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                    if handle:
                        kernel32.CloseHandle(handle)
                        self.pid = pid
                        return True
                else:
                    os.kill(pid, 0)
                    self.pid = pid
                    return True
            except (ValueError, OSError, ProcessLookupError):
                pass

        return False

    def start(self):
        """Start the DAQ service"""
        if self.is_running():
            return True, "Service already running"

        python_exe = get_python_exe()
        daq_service = get_daq_service_path()
        config_path = get_config_path()
        log_file = get_log_file()
        pid_file = get_pid_file()

        # Validate paths
        if not Path(python_exe).exists():
            return False, f"Python not found: {python_exe}"
        if not daq_service.exists():
            return False, f"DAQ service not found: {daq_service}"
        if not config_path.exists():
            return False, f"Config not found: {config_path}"

        try:
            # Start the process
            with open(log_file, 'w') as log:
                if sys.platform == 'win32':
                    # Windows: use CREATE_NO_WINDOW flag
                    CREATE_NO_WINDOW = 0x08000000
                    self.process = subprocess.Popen(
                        [python_exe, str(daq_service), "-c", str(config_path)],
                        cwd=str(daq_service.parent),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=CREATE_NO_WINDOW
                    )
                else:
                    # Linux/Mac
                    self.process = subprocess.Popen(
                        [python_exe, str(daq_service), "-c", str(config_path)],
                        cwd=str(daq_service.parent),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True
                    )

            # Save PID
            pid_file.write_text(str(self.process.pid))
            self.pid = self.process.pid

            # Wait a moment and verify
            time.sleep(2)

            if self.process.poll() is not None:
                # Process exited
                return False, f"Service failed to start. Check {log_file}"

            return True, f"Service started (PID: {self.pid})"

        except Exception as e:
            return False, f"Failed to start: {e}"

    def stop(self):
        """Stop the DAQ service"""
        pid_file = get_pid_file()

        if not self.is_running():
            # Clean up stale PID file
            if pid_file.exists():
                pid_file.unlink()
            return True, "Service not running"

        try:
            if sys.platform == 'win32':
                # Windows: use taskkill
                subprocess.run(['taskkill', '/F', '/PID', str(self.pid)],
                             capture_output=True)
            else:
                # Linux/Mac: send SIGTERM
                os.kill(self.pid, signal.SIGTERM)
                time.sleep(1)
                # Force kill if still running
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

            # Clean up PID file
            if pid_file.exists():
                pid_file.unlink()

            self.pid = None
            return True, "Service stopped"

        except Exception as e:
            return False, f"Failed to stop: {e}"

    def restart(self):
        """Restart the DAQ service"""
        self.stop()
        time.sleep(1)
        return self.start()

    def get_status(self):
        """Get detailed status"""
        status = {
            'running': self.is_running(),
            'pid': self.pid,
            'mqtt_connected': False,
            'acquiring': False,
            'simulation': False,
            'channels': 0
        }

        # Try to get MQTT status
        try:
            import paho.mqtt.client as mqtt

            result = {'data': None}

            def on_message(client, userdata, msg):
                try:
                    result['data'] = json.loads(msg.payload.decode())
                except:
                    pass

            client = mqtt.Client()
            client.on_message = on_message
            client.connect(MQTT_BROKER, MQTT_PORT, 2)
            client.subscribe("nisystem/status/system")
            client.loop_start()

            # Wait for message
            for _ in range(20):  # 2 seconds max
                if result['data']:
                    break
                time.sleep(0.1)

            client.loop_stop()
            client.disconnect()

            if result['data']:
                status['mqtt_connected'] = True
                status['acquiring'] = result['data'].get('acquiring', False)
                status['simulation'] = result['data'].get('simulation_mode', False)
                status['channels'] = result['data'].get('channel_count', 0)
        except:
            pass

        return status


class NISystemLauncherGUI:
    """GUI for the NISystem Launcher"""

    def __init__(self):
        self.service = NISystemService()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} Launcher")
        self.root.geometry("400x350")
        self.root.resizable(False, False)

        # Set icon if available
        try:
            icon_path = get_project_root() / "launcher" / "icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except:
            pass

        self.setup_ui()
        self.update_status()

        # Auto-refresh status every 5 seconds
        self.root.after(5000, self.auto_refresh)

    def setup_ui(self):
        """Setup the UI"""
        # Main frame
        main = ttk.Frame(self.root, padding=20)
        main.pack(fill='both', expand=True)

        # Title
        title = ttk.Label(main, text=APP_NAME, font=('Segoe UI', 18, 'bold'))
        title.pack(pady=(0, 20))

        # Status frame
        status_frame = ttk.LabelFrame(main, text="Status", padding=10)
        status_frame.pack(fill='x', pady=(0, 20))

        # Status labels
        self.status_labels = {}
        status_items = [
            ('service', 'DAQ Service:'),
            ('mqtt', 'MQTT:'),
            ('mode', 'Mode:'),
            ('channels', 'Channels:'),
        ]

        for key, label in status_items:
            row = ttk.Frame(status_frame)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=15).pack(side='left')
            self.status_labels[key] = ttk.Label(row, text="--", width=25)
            self.status_labels[key].pack(side='left')

        # Buttons frame
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill='x', pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.start_service, width=12)
        self.start_btn.pack(side='left', padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop_service, width=12)
        self.stop_btn.pack(side='left', padx=5)

        self.restart_btn = ttk.Button(btn_frame, text="Restart", command=self.restart_service, width=12)
        self.restart_btn.pack(side='left', padx=5)

        # Dashboard button
        dash_frame = ttk.Frame(main)
        dash_frame.pack(fill='x', pady=(10, 0))

        self.dash_btn = ttk.Button(dash_frame, text="Open Dashboard", command=self.open_dashboard, width=20)
        self.dash_btn.pack()

        # Log viewer button
        log_frame = ttk.Frame(main)
        log_frame.pack(fill='x', pady=(10, 0))

        ttk.Button(log_frame, text="View Logs", command=self.view_logs, width=15).pack(side='left', padx=5)
        ttk.Button(log_frame, text="Refresh", command=self.update_status, width=15).pack(side='left', padx=5)

    def update_status(self):
        """Update the status display"""
        status = self.service.get_status()

        # Service status
        if status['running']:
            self.status_labels['service'].config(text=f"Running (PID: {status['pid']})", foreground='green')
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')
        else:
            self.status_labels['service'].config(text="Stopped", foreground='red')
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')

        # MQTT status
        if status['mqtt_connected']:
            self.status_labels['mqtt'].config(text="Connected", foreground='green')
        else:
            self.status_labels['mqtt'].config(text="Disconnected", foreground='red')

        # Mode
        if status['simulation']:
            self.status_labels['mode'].config(text="Simulation", foreground='orange')
        else:
            self.status_labels['mode'].config(text="Hardware", foreground='blue')

        # Channels
        self.status_labels['channels'].config(text=str(status['channels']))

    def auto_refresh(self):
        """Auto-refresh status"""
        self.update_status()
        self.root.after(5000, self.auto_refresh)

    def start_service(self):
        """Start the service"""
        self.start_btn.config(state='disabled')
        success, message = self.service.start()
        if success:
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
        self.update_status()

    def stop_service(self):
        """Stop the service"""
        self.stop_btn.config(state='disabled')
        success, message = self.service.stop()
        if success:
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
        self.update_status()

    def restart_service(self):
        """Restart the service"""
        self.restart_btn.config(state='disabled')
        success, message = self.service.restart()
        if success:
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
        self.restart_btn.config(state='normal')
        self.update_status()

    def open_dashboard(self):
        """Open the dashboard in browser"""
        import webbrowser
        webbrowser.open("http://localhost:5173")

    def view_logs(self):
        """Open the log file"""
        log_file = get_log_file()
        if log_file.exists():
            if sys.platform == 'win32':
                os.startfile(str(log_file))
            else:
                subprocess.run(['xdg-open', str(log_file)])
        else:
            messagebox.showinfo("Info", "No log file found")

    def run(self):
        """Run the GUI"""
        self.root.mainloop()


def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        # Command line mode
        service = NISystemService()
        cmd = sys.argv[1].lower()

        if cmd == 'start':
            success, msg = service.start()
            print(msg)
            sys.exit(0 if success else 1)
        elif cmd == 'stop':
            success, msg = service.stop()
            print(msg)
            sys.exit(0 if success else 1)
        elif cmd == 'restart':
            success, msg = service.restart()
            print(msg)
            sys.exit(0 if success else 1)
        elif cmd == 'status':
            status = service.get_status()
            print(f"Running: {status['running']}")
            print(f"PID: {status['pid']}")
            print(f"MQTT: {'Connected' if status['mqtt_connected'] else 'Disconnected'}")
            print(f"Acquiring: {status['acquiring']}")
            print(f"Simulation: {status['simulation']}")
            print(f"Channels: {status['channels']}")
            sys.exit(0)
        else:
            print(f"Usage: {sys.argv[0]} [start|stop|restart|status]")
            sys.exit(1)
    else:
        # GUI mode
        if HAS_GUI:
            app = NISystemLauncherGUI()
            app.run()
        else:
            print("GUI not available. Use command line: start|stop|restart|status")
            sys.exit(1)


if __name__ == "__main__":
    main()
