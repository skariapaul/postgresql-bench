#!/bin/bash
# PostgreSQL TPC-C benchmark runner
# Auto-tunes shared_buffers, work_mem, VU counts, and NUMA pinning
# based on detected system resources.
#
# Usage:
#   HAMMERDB_DIR=/path/to/HammerDB ./run_tpcc.sh
set -euo pipefail

CONTAINER="pg-tpcc"
IMAGE="postgres:17"
PORT=5432
PG_PASS="postgres"
VOLUME="pg-tpcc-data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HAMMERDB_DIR="${HAMMERDB_DIR:-/home/paskaria/HammerDB}"
RESULTS_DIR="$SCRIPT_DIR/results/tpcc"
LOG="$RESULTS_DIR/tpcc-$(date +%Y%m%d-%H%M%S).log"
TMPDIR_BENCH="$(mktemp -d /tmp/pg-bench-tpcc-XXXXXX)"
trap 'rm -rf "$TMPDIR_BENCH"' EXIT

mkdir -p "$RESULTS_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────
clamp() { local v=$1 lo=$2 hi=$3; (( v < lo )) && v=$lo; (( v > hi )) && v=$hi; echo $v; }

# Count logical CPUs in a cpulist string like "0-15,64-79"
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

# NUMA: pin to node 0 when multiple NUMA nodes exist
NUMA_NODES=$(ls /sys/devices/system/node/ 2>/dev/null | grep -c '^node[0-9]' || echo 1)
DOCKER_NUMA_ARGS=()
if [[ $NUMA_NODES -gt 1 ]]; then
  NODE0_CPUS=$(cat /sys/devices/system/node/node0/cpulist 2>/dev/null || echo "")
  if [[ -n "$NODE0_CPUS" ]]; then
    # Pin CPUs to node 0 for cache locality, but NOT --cpuset-mems:
    # restricting memory to a single NUMA node caps available RAM to that
    # node's physical memory (~94 GB here), causing OOM with large shared_buffers.
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

# ── Compute PostgreSQL parameters ─────────────────────────────────────────────
# shared_buffers: 25% RAM, 1 GB min, 80 GB max
SHM_GB=$(clamp $(( TOTAL_RAM_GB / 4 )) 1 80)
# effective_cache_size: 75% RAM
ECG=$(clamp $(( TOTAL_RAM_GB * 3 / 4 )) 1 $(( TOTAL_RAM_GB - 1 )) )
# work_mem: 4 MB per GB RAM, 128 MB min, 2 GB max
WORK_MEM_MB=$(clamp $(( TOTAL_RAM_GB * 4 )) 128 2048)
# maintenance_work_mem: 5 MB per GB RAM, 256 MB min, 4 GB max
MAINT_MEM_MB=$(clamp $(( TOTAL_RAM_GB * 5 )) 256 4096)
# parallelism
MAX_WORKERS=$(clamp $(( BENCH_CPUS * 2 )) 8 256)
MAX_PARALLEL=$(clamp $BENCH_CPUS 4 128)
GATHER=$(clamp $(( BENCH_CPUS / 4 )) 1 8)

# ── Compute HammerDB parameters ───────────────────────────────────────────────
# Build VUs: CPUs/8, 4 min, 16 max
BUILD_VU=$(clamp $(( BENCH_CPUS / 8 )) 4 16)
# Run VUs: CPUs/2, 8 min, 64 max
RUN_VU=$(clamp $(( BENCH_CPUS / 2 )) 8 64)
# Warehouses: 4× run VUs to keep ~4 W/VU ratio
WAREHOUSES=$(clamp $(( RUN_VU * 4 )) 64 2048)

# ── Generate postgresql.conf ──────────────────────────────────────────────────
PG_CONF="$TMPDIR_BENCH/postgresql.conf"
cat > "$PG_CONF" <<EOF
listen_addresses = '*'
max_connections = 200

shared_buffers             = ${SHM_GB}GB
effective_cache_size       = ${ECG}GB
work_mem                   = ${WORK_MEM_MB}MB
maintenance_work_mem       = ${MAINT_MEM_MB}MB
huge_pages                 = try

wal_buffers                = 64MB
wal_compression            = on
min_wal_size               = 4GB
max_wal_size               = 16GB
checkpoint_completion_target = 0.9
checkpoint_warning         = 0
synchronous_commit         = off

max_worker_processes           = ${MAX_WORKERS}
max_parallel_workers           = ${MAX_PARALLEL}
max_parallel_workers_per_gather = ${GATHER}
max_parallel_maintenance_workers = $(clamp $(( BENCH_CPUS / 4 )) 2 16)

random_page_cost           = 1.1
seq_page_cost              = 1.0
effective_io_concurrency   = 64

jit                        = off
autovacuum                 = on
autovacuum_max_workers     = $(clamp $(( BENCH_CPUS / 8 )) 3 8)
autovacuum_vacuum_cost_delay = 2ms

log_min_duration_statement = -1
logging_collector          = off
EOF

# ── Generate build TCL ────────────────────────────────────────────────────────
BUILD_TCL="$TMPDIR_BENCH/tpcc_build.tcl"
cat > "$BUILD_TCL" <<EOF
dbset db pg
dbset bm TPC-C
diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer
diset tpcc pg_superuser postgres
diset tpcc pg_superuserpass postgres
diset tpcc pg_defaultdbase postgres
diset tpcc pg_user tpcc
diset tpcc pg_pass tpcc
diset tpcc pg_dbase tpcc
diset tpcc pg_tspace pg_default
diset tpcc pg_count_ware ${WAREHOUSES}
diset tpcc pg_num_vu ${BUILD_VU}
diset tpcc pg_allwarehouse true
diset tpcc pg_partition false
diset tpcc pg_storedprocs true
diset tpcc pg_vacuum true
puts "SCHEMA BUILD STARTED"
buildschema
puts "SCHEMA BUILD COMPLETED"
EOF

# ── Generate run TCL ──────────────────────────────────────────────────────────
RUN_TCL="$TMPDIR_BENCH/tpcc_run.tcl"
cat > "$RUN_TCL" <<EOF
set tmpdir \$::env(TMP)
dbset db pg
dbset bm TPC-C
diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer
diset tpcc pg_superuser postgres
diset tpcc pg_superuserpass postgres
diset tpcc pg_defaultdbase postgres
diset tpcc pg_user tpcc
diset tpcc pg_pass tpcc
diset tpcc pg_dbase tpcc
diset tpcc pg_driver timed
diset tpcc pg_rampup 2
diset tpcc pg_duration 10
diset tpcc pg_allwarehouse true
diset tpcc pg_vacuum true
diset tpcc pg_timeprofile true
diset tpcc pg_total_iterations 10000000
loadscript
puts "TEST STARTED"
vuset vu ${RUN_VU}
vuset logtotemp 1
vucreate
set jobid [ vurun ]
vudestroy
puts "TEST COMPLETE"
set of [ open \$tmpdir/pg_tprocc w ]
puts \$of \$jobid
close \$of
EOF

# ── Print config summary ──────────────────────────────────────────────────────
echo "=== PostgreSQL TPC-C Benchmark ==="
printf "System         : %d GB RAM, %d total CPUs\n" "$TOTAL_RAM_GB" "$TOTAL_CPUS"
printf "NUMA           : %s\n" "$NUMA_DESC"
printf "shared_buffers : %d GB\n" "$SHM_GB"
printf "work_mem       : %d MB\n" "$WORK_MEM_MB"
printf "Build VUs      : %d    Warehouses: %d\n" "$BUILD_VU" "$WAREHOUSES"
printf "Run VUs        : %d\n" "$RUN_VU"
printf "Log            : %s\n" "$LOG"
echo ""

# ── Start container ───────────────────────────────────────────────────────────
echo "[1/4] Starting $CONTAINER..."
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
echo "[2/4] Building TPC-C schema (${WAREHOUSES} warehouses, ${BUILD_VU} VUs)..."
cd "$HAMMERDB_DIR"
TMP=/tmp ./hammerdbcli auto "$BUILD_TCL" 2>&1 | tee -a "$LOG"

# ── Run benchmark ─────────────────────────────────────────────────────────────
echo ""
echo "[3/4] Running TPC-C (${RUN_VU} VUs, 2 min ramp + 10 min timed)..."
TMP=/tmp ./hammerdbcli auto "$RUN_TCL" 2>&1 | tee -a "$LOG"

# ── Results ───────────────────────────────────────────────────────────────────
echo ""
echo "[4/4] Complete. Log: $LOG"
grep -oP 'System achieved.*' "$LOG" | tail -1 || echo "(see log for NOPM/TPM)"
echo ""
echo "=== TPC-C Complete ==="
