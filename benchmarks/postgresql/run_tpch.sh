#!/bin/bash
# PostgreSQL TPC-H benchmark runner
# System: AMD EPYC 9555P, 64C/128T, NPS4, 377 GiB RAM, NVMe
# Pinned to NUMA node0 (CPUs 0-15, 64-79 = 32 logical CPUs, 2 CCDs)
#
# Usage:
#   ./run_tpch.sh [sf10|sf100]   (default: sf10)
#
# sf10  — ~10 GB raw data, schema loads in ~10-20 min, good for validation
# sf100 — ~100 GB raw data, schema loads in ~1-2 hours, production benchmark
set -euo pipefail

SF="${1:-sf10}"
if [[ "$SF" != "sf10" && "$SF" != "sf100" ]]; then
  echo "Usage: $0 [sf10|sf100]"
  exit 1
fi

CONTAINER="pg-tpch"
IMAGE="postgres:17"
PORT=5432
PG_PASS="postgres"
VOLUME="pg-tpch-${SF}-data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HAMMERDB_DIR="${HAMMERDB_DIR:-/home/paskaria/HammerDB}"
RESULTS_DIR="$SCRIPT_DIR/results/tpch"
LOG="$RESULTS_DIR/tpch-${SF}-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "$RESULTS_DIR"

echo "=== PostgreSQL TPC-H Benchmark ($SF) ==="
echo "Image    : $IMAGE"
echo "CPUs     : 0-15,64-79 (NUMA node0, 32 logical CPUs)"
echo "Scale    : $SF"
echo "Log      : $LOG"
echo ""

# ── Start container ──────────────────────────────────────────────────────────
echo "[1/5] Starting $CONTAINER..."
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d \
  --name "$CONTAINER" \
  --cpuset-cpus "0-15,64-79" \
  --cpuset-mems 0 \
  --shm-size=8g \
  -e POSTGRES_PASSWORD="$PG_PASS" \
  -p ${PORT}:5432 \
  -v "${VOLUME}:/var/lib/postgresql/data" \
  -v "$SCRIPT_DIR/docker/tpch/postgresql.conf:/etc/postgresql/postgresql.conf:ro" \
  "$IMAGE" \
  postgres -c config_file=/etc/postgresql/postgresql.conf

echo "Waiting for PostgreSQL to be ready..."
until docker exec "$CONTAINER" pg_isready -U postgres -q 2>/dev/null; do sleep 2; done
echo "PostgreSQL is ready."

# ── Build schema ─────────────────────────────────────────────────────────────
echo ""
echo "[2/5] Building TPC-H schema ($SF)..."
if [[ "$SF" == "sf10" ]]; then
  echo "      Expect ~10-20 minutes..."
  BUILD_SCRIPT="$SCRIPT_DIR/tcl/tpch/tpch_build_sf10.tcl"
else
  echo "      Expect ~1-2 hours for SF100 on NVMe..."
  BUILD_SCRIPT="$SCRIPT_DIR/tcl/tpch/tpch_build_sf100.tcl"
fi

cd "$HAMMERDB_DIR"
TMP=/tmp ./hammerdbcli auto "$BUILD_SCRIPT" 2>&1 | tee -a "$LOG"

# ── Power test ────────────────────────────────────────────────────────────────
echo ""
echo "[3/5] Running TPC-H power test (1 VU, dop=8)..."
TMP=/tmp ./hammerdbcli auto "$SCRIPT_DIR/tcl/tpch/tpch_power_${SF}.tcl" 2>&1 | tee -a "$LOG"

# ── Throughput test ───────────────────────────────────────────────────────────
echo ""
echo "[4/5] Running TPC-H throughput test (5 VUs, dop=3)..."
TMP=/tmp ./hammerdbcli auto "$SCRIPT_DIR/tcl/tpch/tpch_throughput_${SF}.tcl" 2>&1 | tee -a "$LOG"

# ── Results ───────────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Complete. Log saved: $LOG"
echo "      Review the log for QphH (Query-per-hour H-Scoring) metrics."
echo ""
echo "=== TPC-H ($SF) Complete ==="
