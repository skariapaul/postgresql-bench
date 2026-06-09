#!/bin/bash
# Power monitoring library — source this file, do not execute directly.
#
# Detects AMD RAPL (via powercap) or IPMI and samples package power at a
# fixed interval throughout each benchmark phase, writing a CSV log.
#
# Usage:
#   source "$(dirname "$0")/lib/power_monitor.sh"
#   power_detect                            # sets POWER_METHOD, prints it
#   power_monitor_start "build" "$POWER_LOG"
#   ... run benchmark phase ...
#   power_monitor_stop
#   power_summary "$POWER_LOG"             # prints min/avg/max per phase

POWER_METHOD=""
POWER_MONITOR_PID=""
POWER_INTERVAL=5   # seconds between samples

RAPL_ENERGY="/sys/class/powercap/intel-rapl:0/energy_uj"
RAPL_MAXRANGE="/sys/class/powercap/intel-rapl:0/max_energy_range_uj"

# ── Detect available method ────────────────────────────────────────────────────
power_detect() {
    if [[ -r "$RAPL_ENERGY" ]]; then
        POWER_METHOD="rapl"
    elif command -v ipmitool &>/dev/null && ipmitool dcmi power reading &>/dev/null 2>&1; then
        POWER_METHOD="ipmi"
    else
        POWER_METHOD="none"
    fi
    echo "$POWER_METHOD"
}

# ── Internal samplers ──────────────────────────────────────────────────────────
_power_watts_rapl() {
    local maxrange e1 e2 t1 t2
    maxrange=$(cat "$RAPL_MAXRANGE" 2>/dev/null || echo 1000000000000)
    e1=$(cat "$RAPL_ENERGY"); t1=$(date +%s%N)
    sleep "$POWER_INTERVAL"
    e2=$(cat "$RAPL_ENERGY"); t2=$(date +%s%N)
    # Handle counter wraparound
    (( e2 < e1 )) && e2=$(( e2 + maxrange ))
    local de=$(( e2 - e1 ))
    local dt=$(( (t2 - t1) / 1000 ))   # nanoseconds → microseconds
    # de [µJ] / dt [µs] = Watts
    awk "BEGIN {printf \"%.1f\", $de / $dt}"
}

_power_watts_ipmi() {
    ipmitool dcmi power reading 2>/dev/null | awk '/Instantaneous/{print $4}'
}

# ── Background monitor loop ────────────────────────────────────────────────────
_power_loop() {
    local phase="$1" csvfile="$2"
    while true; do
        local ts watts
        ts=$(date +%Y-%m-%dT%H:%M:%S)
        if [[ "$POWER_METHOD" == "rapl" ]]; then
            watts=$(_power_watts_rapl)        # already sleeps POWER_INTERVAL
        else
            watts=$(_power_watts_ipmi)
            sleep "$POWER_INTERVAL"
        fi
        [[ -n "$watts" ]] && echo "${ts},${phase},${watts}" >> "$csvfile"
    done
}

# ── Public API ─────────────────────────────────────────────────────────────────
power_monitor_start() {
    local phase="$1" csvfile="$2"
    [[ "$POWER_METHOD" == "none" ]] && return 0
    _power_loop "$phase" "$csvfile" &
    POWER_MONITOR_PID=$!
}

power_monitor_stop() {
    [[ -z "$POWER_MONITOR_PID" ]] && return 0
    kill "$POWER_MONITOR_PID" 2>/dev/null
    wait "$POWER_MONITOR_PID" 2>/dev/null || true
    POWER_MONITOR_PID=""
}

power_summary() {
    local csvfile="$1"
    [[ "$POWER_METHOD" == "none" ]] && return 0
    [[ ! -s "$csvfile" ]] && { echo "(no power samples recorded)"; return 0; }
    echo ""
    echo "=== Power Consumption (package-0) ==="
    printf "%-22s %7s %7s %7s %7s\n" "Phase" "Samples" "Min W" "Avg W" "Max W"
    printf "%-22s %7s %7s %7s %7s\n" "-----" "-------" "-----" "-----" "-----"
    awk -F',' '
        {
            phase=$2; w=$3+0
            n[phase]++; s[phase]+=w
            if (!(phase in lo) || w<lo[phase]) lo[phase]=w
            if (!(phase in hi) || w>hi[phase]) hi[phase]=w
        }
        END {
            for (p in n)
                printf "%-22s %7d %7.0f %7.0f %7.0f\n",
                    p, n[p], lo[p], s[p]/n[p], hi[p]
        }
    ' "$csvfile" | sort
    echo ""
    echo "Power log: $csvfile"
}
