#!/bin/sh
### BEGIN INIT INFO
# Provides:          crio_node
# Required-Start:    $network $remote_fs
# Required-Stop:     $network $remote_fs
# Default-Start:     3 5
# Default-Stop:      0 1 6
# Description:       NISystem cRIO Node V2 Service with auto-restart
### END INIT INFO

WORKDIR=/home/admin/nisystem
PIDFILE=/var/run/crio_node.pid
LOGFILE=/var/log/crio_node_v2.log
RESTART_DELAY=5

# Wrapper that auto-restarts on crash (run_crio_v2.py loads mqtt_creds.json)
run_with_restart() {
    while true; do
        echo "$(date): Starting cRIO Node V2..." >> $LOGFILE
        cd $WORKDIR
        export MALLOC_CHECK_=0
        python3 run_crio_v2.py >> $LOGFILE 2>&1
        EXIT_CODE=$?
        echo "$(date): cRIO Node exited with code $EXIT_CODE, restarting in ${RESTART_DELAY}s..." >> $LOGFILE
        sleep $RESTART_DELAY
    done
}

case "$1" in
  start)
    echo "Starting cRIO Node V2 Service..."
    if [ -f $PIDFILE ] && kill -0 $(cat $PIDFILE) 2>/dev/null; then
      echo "Service already running (PID: $(cat $PIDFILE))"
      exit 0
    fi
    # Fully detach from SSH session (close all FDs so SSH returns immediately)
    run_with_restart </dev/null >>/dev/null 2>&1 &
    echo $! > $PIDFILE
    echo "Started with PID $(cat $PIDFILE)"
    ;;
  stop)
    echo "Stopping cRIO Node V2 Service..."
    if [ -f $PIDFILE ]; then
      WRAPPER_PID=$(cat $PIDFILE)
      # Kill wrapper children first, then wrapper
      pkill -P $WRAPPER_PID 2>/dev/null
      kill $WRAPPER_PID 2>/dev/null
      sleep 1
      # Force kill anything that survived
      kill -9 $WRAPPER_PID 2>/dev/null
    fi
    # Belt-and-suspenders: kill ALL cRIO-related python processes
    pkill -9 -f 'run_crio_v2.py' 2>/dev/null
    pkill -9 -f 'python3 -m crio_node' 2>/dev/null
    rm -f $PIDFILE
    echo "Stopped"
    ;;
  restart)
    $0 stop
    sleep 2
    $0 start
    ;;
  status)
    if [ -f $PIDFILE ] && kill -0 $(cat $PIDFILE) 2>/dev/null; then
      echo "cRIO Node V2 Service is running (PID: $(cat $PIDFILE))"
      pgrep -fa 'run_crio_v2.py' 2>/dev/null || true
    else
      echo "cRIO Node V2 Service is not running"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
exit 0
