#!/bin/bash
# PostgreSQL TPC-H benchmark runner
# Auto-tunes shared_buffers, work_mem, parallelism, and NUMA pinning
# based on detected system resources.
#
# Usage:
#   HAMMERDB_DIR=/path/to/HammerDB ./run_tpch.sh [sf10|sf100]   (default: sf10)
#
# sf10  — ~10 GB raw data, ~15-30 min load,  good for validation
# sf100 — ~100 GB raw data, ~2-4 h load,     production benchmark
set -euo pipefail

SF="${1:-sf10}"
if [[ "$SF" != "sf10" && "$SF" != "sf100" ]]; then
  echo "Usage: $0 [sf10|sf100]"
  exit 1
fi
SCALE_FACTOR="${SF#sf}"   # "10" or "100"

CONTAINER="pg-tpch"
IMAGE="postgres:17"
PORT=5432
PG_PASS="postgres"
VOLUME="pg-tpch-${SF}-data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HAMMERDB_DIR="${HAMMERDB_DIR:-/home/paskaria/HammerDB}"
RESULTS_DIR="$SCRIPT_DIR/results/tpch"
LOG="$RESULTS_DIR/tpch-${SF}-$(date +%Y%m%d-%H%M%S).log"
TMPDIR_BENCH="$(mktemp -d /tmp/pg-bench-tpch-XXXXXX)"
trap 'rm -rf "$TMPDIR_BENCH"' EXIT

mkdir -p "$RESULTS_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────
clamp() { local v=$1 lo=$2 hi=$3; (( v < lo )) && v=$lo; (( v > hi )) && v=$hi; echo $v; }

count_cpulist() {
  local n=0 seg
  local IFS=','
  for seg in $1; do
    if [[ $seg == *-* ]]; then
      (( n += ${seg#*-} - ${seg%-*} + 1 ))
    else
      (( n++ ))
    fi
  done
  echo $n
}

# ── Detect resources ──────────────────────────────────────────────────────────
TOTAL_RAM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
TOTAL_CPUS=$(nproc)

NUMA_NODES=$(ls /sys/devices/system/node/ 2>/dev/null | grep -c '^node[0-9]' || echo 1)
DOCKER_NUMA_ARGS=()
if [[ $NUMA_NODES -gt 1 ]]; then
  NODE0_CPUS=$(cat /sys/devices/system/node/node0/cpulist 2>/dev/null || echo "")
  if [[ -n "$NODE0_CPUS" ]]; then
    # Pin CPUs to node 0 for cache locality, but NOT --cpuset-mems:
    # restricting memory to a single NUMA node caps available RAM to that
    # node's physical memory, causing OOM when shared_buffers exceeds it.
    DOCKER_NUMA_ARGS=(--cpuset-cpus "$NODE0_CPUS")
    BENCH_CPUS=$(count_cpulist "$NODE0_CPUS")
    NUMA_DESC="node0 CPUs ($NODE0_CPUS, ${BENCH_CPUS} logical CPUs), memory unrestricted"
  else
    DOCKER_NUMA_ARGS=()
    BENCH_CPUS=$TOTAL_CPUS
    NUMA_DESC="all ${TOTAL_CPUS} CPUs"
  fi
else
  DOCKER_NUMA_ARGS=()
  BENCH_CPUS=$TOTAL_CPUS
  NUMA_DESC="all ${TOTAL_CPUS} CPUs (single NUMA node)"
fi

# ── Check disk space ──────────────────────────────────────────────────────────
FREE_DISK_GB=$(df -BG "$SCRIPT_DIR" | tail -1 | awk '{print $4}' | tr -d 'G')
if [[ "$SF" == "sf100" && $FREE_DISK_GB -lt 200 ]]; then
  echo "WARNING: SF100 needs ~200 GB free disk; only ${FREE_DISK_GB} GB available."
  echo "         Consider using sf10 for a lighter run."
  echo "         Proceeding anyway — run may fail if disk fills up."
  echo ""
elif [[ "$SF" == "sf10" && $FREE_DISK_GB -lt 20 ]]; then
  echo "ERROR: SF10 needs ~20 GB free disk; only ${FREE_DISK_GB} GB available."
  exit 1
fi

# ── Compute HammerDB parallelism ──────────────────────────────────────────────
# Build threads: CPUs, 4 min, 16 max (HammerDB TCL threads plateau ~16)
BUILD_THREADS=$(clamp $BENCH_CPUS 4 16)
# Throughput streams: CPUs/8, 2 min, 10 max
THRU_VU=$(clamp $(( BENCH_CPUS / 8 )) 2 10)
# Power test degree-of-parallel: CPUs/4, 2 min, 16 max
POWER_DOP=$(clamp $(( BENCH_CPUS / 4 )) 2 16)
# Throughput degree-of-parallel: CPUs / (2*THRU_VU), 1 min, 8 max
THRU_DOP=$(clamp $(( BENCH_CPUS / (THRU_VU * 2) )) 1 8)

# ── Compute PostgreSQL parameters ─────────────────────────────────────────────
# shared_buffers: 40% RAM, 1 GB min
# Cap so there's enough headroom for work_mem × streams
RAW_SHM=$(( TOTAL_RAM_GB * 2 / 5 ))
SHM_GB=$(clamp $RAW_SHM 1 $(( TOTAL_RAM_GB * 9 / 10 )) )

# effective_cache_size: 70% RAM
ECG=$(clamp $(( TOTAL_RAM_GB * 7 / 10 )) 1 $(( TOTAL_RAM_GB - 1 )) )

# work_mem: leave 85% RAM after shared_buffers for peak parallel sorts
# Peak streams = THRU_VU × (THRU_DOP + 1); cap at 8 GB
AVAIL_FOR_WORK_MB=$(( (TOTAL_RAM_GB * 85 / 100 - SHM_GB) * 1024 ))
PEAK_STREAMS=$(( THRU_VU * (THRU_DOP + 1) ))
WORK_MEM_MB=$(clamp $(( AVAIL_FOR_WORK_MB / PEAK_STREAMS )) 512 8192)

MAINT_MEM_MB=$(clamp $(( TOTAL_RAM_GB * 8 )) 512 8192)
MAX_WORKERS=$(clamp $(( BENCH_CPUS * 2 )) 8 256)
MAX_PARALLEL=$(clamp $BENCH_CPUS 4 128)
MAX_GATHER=$(clamp $(( BENCH_CPUS / 2 )) 2 16)

# ── Generate postgresql.conf ──────────────────────────────────────────────────
PG_CONF="$TMPDIR_BENCH/postgresql.conf"
cat > "$PG_CONF" <<EOF
listen_addresses = '*'
max_connections = 64

shared_buffers               = ${SHM_GB}GB
effective_cache_size         = ${ECG}GB
work_mem                     = ${WORK_MEM_MB}MB
maintenance_work_mem         = ${MAINT_MEM_MB}MB
huge_pages                   = try

wal_level                    = minimal
max_wal_senders              = 0
wal_buffers                  = 1024MB
min_wal_size                 = 20GB
max_wal_size                 = 40GB
checkpoint_completion_target = 0.9
synchronous_commit           = local

max_worker_processes             = ${MAX_WORKERS}
max_parallel_workers             = ${MAX_PARALLEL}
max_parallel_workers_per_gather  = ${MAX_GATHER}
max_parallel_maintenance_workers = $(clamp $(( BENCH_CPUS / 4 )) 2 16)

random_page_cost           = 1.1
seq_page_cost              = 1.0
effective_io_concurrency   = 64

jit                        = on
autovacuum                 = off

log_min_duration_statement = -1
logging_collector          = off
EOF

# ── Generate build TCL ────────────────────────────────────────────────────────
BUILD_TCL="$TMPDIR_BENCH/tpch_build.tcl"
cat > "$BUILD_TCL" <<EOF
dbset db pg
dbset bm TPC-H
diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer
diset tpch pg_scale_fact ${SCALE_FACTOR}
diset tpch pg_num_tpch_threads ${BUILD_THREADS}
diset tpch pg_tpch_superuser postgres
diset tpch pg_tpch_superuserpass postgres
diset tpch pg_tpch_defaultdbase postgres
diset tpch pg_tpch_user tpch
diset tpch pg_tpch_pass tpch
diset tpch pg_tpch_dbase tpch
diset tpch pg_tpch_tspace pg_default
puts "SCHEMA BUILD STARTED"
buildschema
puts "SCHEMA BUILD COMPLETED"
EOF

# ── Generate power test TCL ───────────────────────────────────────────────────
POWER_TCL="$TMPDIR_BENCH/tpch_power.tcl"
cat > "$POWER_TCL" <<EOF
set tmpdir \$::env(TMP)
dbset db pg
dbset bm TPC-H
diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer
diset tpch pg_scale_fact ${SCALE_FACTOR}
diset tpch pg_tpch_user tpch
diset tpch pg_tpch_pass tpch
diset tpch pg_tpch_dbase tpch
diset tpch pg_total_querysets 1
diset tpch pg_degree_of_parallel ${POWER_DOP}
loadscript
puts "TEST STARTED"
vuset vu 1
vuset logtotemp 1
vucreate
set jobid [ vurun ]
vudestroy
puts "TEST COMPLETE"
set of [ open \$tmpdir/pg_tproch_power w ]
puts \$of \$jobid
close \$of
EOF

# ── Generate throughput test TCL ──────────────────────────────────────────────
THRU_TCL="$TMPDIR_BENCH/tpch_throughput.tcl"
cat > "$THRU_TCL" <<EOF
set tmpdir \$::env(TMP)
dbset db pg
dbset bm TPC-H
diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer
diset tpch pg_scale_fact ${SCALE_FACTOR}
diset tpch pg_tpch_user tpch
diset tpch pg_tpch_pass tpch
diset tpch pg_tpch_dbase tpch
diset tpch pg_total_querysets 1
diset tpch pg_degree_of_parallel ${THRU_DOP}
loadscript
puts "TEST STARTED"
vuset vu ${THRU_VU}
vuset logtotemp 1
vucreate
set jobid [ vurun ]
vudestroy
puts "TEST COMPLETE"
set of [ open \$tmpdir/pg_tproch_throughput w ]
puts \$of \$jobid
close \$of
EOF

# ── Print config summary ──────────────────────────────────────────────────────
echo "=== PostgreSQL TPC-H Benchmark ($SF) ==="
printf "System           : %d GB RAM, %d total CPUs\n" "$TOTAL_RAM_GB" "$TOTAL_CPUS"
printf "NUMA             : %s\n" "$NUMA_DESC"
printf "Scale factor     : %s\n" "$SF"
printf "shared_buffers   : %d GB\n" "$SHM_GB"
printf "work_mem         : %d MB  (peak streams: %d)\n" "$WORK_MEM_MB" "$PEAK_STREAMS"
printf "Build threads    : %d\n" "$BUILD_THREADS"
printf "Power test       : 1 VU, dop=%d\n" "$POWER_DOP"
printf "Throughput test  : %d VUs, dop=%d\n" "$THRU_VU" "$THRU_DOP"
printf "Log              : %s\n" "$LOG"
echo ""

# ── Start container ───────────────────────────────────────────────────────────
echo "[1/5] Starting $CONTAINER..."
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d \
  --name "$CONTAINER" \
  "${DOCKER_NUMA_ARGS[@]+"${DOCKER_NUMA_ARGS[@]}"}" \
  --shm-size="${SHM_GB}g" \
  -e POSTGRES_PASSWORD="$PG_PASS" \
  -p ${PORT}:5432 \
  -v "${VOLUME}:/var/lib/postgresql/data" \
  -v "${PG_CONF}:/etc/postgresql/postgresql.conf:ro" \
  "$IMAGE" \
  postgres -c config_file=/etc/postgresql/postgresql.conf

echo "Waiting for PostgreSQL..."
until docker exec "$CONTAINER" pg_isready -U postgres -q 2>/dev/null; do sleep 2; done
echo "Ready."

# ── Build schema ──────────────────────────────────────────────────────────────
echo ""
echo "[2/5] Building TPC-H schema ($SF, ${BUILD_THREADS} threads)..."
cd "$HAMMERDB_DIR"
TMP=/tmp ./hammerdbcli auto "$BUILD_TCL" 2>&1 | tee -a "$LOG"

# ── Power test ────────────────────────────────────────────────────────────────
echo ""
echo "[3/5] Running power test (1 VU, dop=${POWER_DOP})..."
TMP=/tmp ./hammerdbcli auto "$POWER_TCL" 2>&1 | tee -a "$LOG"

# ── Throughput test ───────────────────────────────────────────────────────────
echo ""
echo "[4/5] Running throughput test (${THRU_VU} VUs, dop=${THRU_DOP})..."
TMP=/tmp ./hammerdbcli auto "$THRU_TCL" 2>&1 | tee -a "$LOG"

# ── Results ───────────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Complete. Log: $LOG"
echo "      Review the log for QphH = sqrt(Power × Throughput) metrics."
echo ""
echo "=== TPC-H ($SF) Complete ==="
