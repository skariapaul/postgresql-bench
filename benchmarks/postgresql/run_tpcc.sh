#!/bin/bash
# PostgreSQL TPC-C benchmark runner
# System: AMD EPYC 9555P, 64C/128T, NPS4, 377 GiB RAM, NVMe
# Pinned to NUMA node0 (CPUs 0-15, 64-79 = 32 logical CPUs, 2 CCDs)
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

mkdir -p "$RESULTS_DIR"

echo "=== PostgreSQL TPC-C Benchmark ==="
echo "Image    : $IMAGE"
echo "CPUs     : 0-15,64-79 (NUMA node0, 32 logical CPUs)"
echo "Memory   : --cpuset-mems 0"
echo "Log      : $LOG"
echo ""

# ── Start container ──────────────────────────────────────────────────────────
echo "[1/4] Starting $CONTAINER..."
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d \
  --name "$CONTAINER" \
  --cpuset-cpus "0-15,64-79" \
  --cpuset-mems 0 \
  --shm-size=4g \
  -e POSTGRES_PASSWORD="$PG_PASS" \
  -p ${PORT}:5432 \
  -v "${VOLUME}:/var/lib/postgresql/data" \
  -v "$SCRIPT_DIR/docker/tpcc/postgresql.conf:/etc/postgresql/postgresql.conf:ro" \
  "$IMAGE" \
  postgres -c config_file=/etc/postgresql/postgresql.conf

echo "Waiting for PostgreSQL to be ready..."
until docker exec "$CONTAINER" pg_isready -U postgres -q 2>/dev/null; do sleep 2; done
echo "PostgreSQL is ready."

# ── Build schema ─────────────────────────────────────────────────────────────
echo ""
echo "[2/4] Building TPC-C schema (64 warehouses, 8 VUs)..."
echo "      Expect ~15-25 minutes..."
cd "$HAMMERDB_DIR"
TMP=/tmp ./hammerdbcli auto "$SCRIPT_DIR/tcl/tpcc/tpcc_build.tcl" 2>&1 | tee -a "$LOG"

# ── Run benchmark ─────────────────────────────────────────────────────────────
echo ""
echo "[3/4] Running TPC-C benchmark (32 VUs, 2m ramp + 10m timed)..."
TMP=/tmp ./hammerdbcli auto "$SCRIPT_DIR/tcl/tpcc/tpcc_run_32vu.tcl" 2>&1 | tee -a "$LOG"

# ── Extract result ────────────────────────────────────────────────────────────
echo ""
echo "[4/4] Results:"
NOPM=$(grep -oP 'TPM:\s+\K[0-9,]+' "$LOG" | tail -1 | tr -d ',' || echo "see log")
echo "Log saved: $LOG"
echo "Check the log for NOPM (New Orders Per Minute) and TPM figures."
echo ""
echo "=== TPC-C Complete ==="
