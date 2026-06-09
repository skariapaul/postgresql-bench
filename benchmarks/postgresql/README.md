# PostgreSQL TPC-C & TPC-H Benchmark

End-to-end benchmark procedure for PostgreSQL using [HammerDB](https://www.hammerdb.com/) on AMD EPYC bare-metal. Covers Docker setup, NUMA-aware CPU pinning, database tuning, and reproducible benchmark runs for both OLTP (TPC-C) and OLAP (TPC-H) workloads.

---

## Reference System

| Component | Detail |
|-----------|--------|
| CPU | AMD EPYC 9555P — 64 cores / 128 threads, single socket |
| NUMA | NPS4 — 4 nodes; node0 = CPUs 0-15, 64-79 (32 logical CPUs) |
| RAM | 377 GiB DDR5 |
| Storage | 465 GB NVMe SSD |
| OS | Ubuntu 24.04 LTS |
| PostgreSQL | 17 (Docker image `postgres:17`) |
| HammerDB | 5.0 |

---

## Requirements

- Docker Engine 20.10+ (`docker run`, no Compose needed)
- HammerDB 5.0 — [download](https://github.com/TPC-Council/HammerDB/releases)
- `libpq5` — PostgreSQL client library for HammerDB's TCL driver
- ~30 GB free disk for TPC-C (64W) / ~50 GB for TPC-H SF10 / ~200 GB for TPC-H SF100
- 16+ GB RAM

> **Note:** `listen_addresses = '*'` is set in the provided `postgresql.conf` so PostgreSQL listens on all container interfaces, allowing HammerDB on the host to reach it via Docker's port forwarding.

### Install dependencies (Ubuntu/Debian)

```bash
# Docker
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io
sudo usermod -aG docker $USER && newgrp docker

# PostgreSQL client library (required by HammerDB)
sudo apt-get install -y libpq5
```

### Install HammerDB

```bash
wget https://github.com/TPC-Council/HammerDB/releases/download/v5.0/HammerDB-5.0-Linux.tar.gz
tar -xzf HammerDB-5.0-Linux.tar.gz
export HAMMERDB_DIR=$PWD/HammerDB   # set this before running benchmarks
```

---

## NUMA Topology (AMD EPYC NPS4)

With NPS4 the 64 physical cores are split across 4 NUMA nodes. Pinning the container's CPUs to a single node eliminates cross-node scheduler jitter and gives consistent results.

```
Node 0: CPUs 0-15, 64-79   ← used for benchmarks (32 logical / 16 physical)
Node 1: CPUs 16-31, 80-95
Node 2: CPUs 32-47, 96-111
Node 3: CPUs 48-63, 112-127
```

> **Important:** the automated scripts use `--cpuset-cpus` only — **not** `--cpuset-mems`. Adding `--cpuset-mems 0` restricts all memory allocations to NUMA node 0's physical RAM (~94 GB on this system). With `shared_buffers = 100 GB`, the OOM killer will terminate PostgreSQL during checkpoint even when the system has hundreds of GB free on other nodes.

---

## Auto-scaling

Both `run_tpcc.sh` and `run_tpch.sh` detect system resources at runtime and compute all tuning parameters automatically. No manual editing required.

| What is detected | How it is used |
|-----------------|----------------|
| Total RAM (`/proc/meminfo`) | `shared_buffers` (25% for OLTP / 40% for OLAP), `work_mem`, `maintenance_work_mem` |
| Logical CPUs (`nproc`) | VU counts, warehouse count, `max_parallel_workers`, `max_parallel_workers_per_gather` |
| NUMA topology (`/sys/devices/system/node/`) | Auto-pins to NUMA node 0 when multiple nodes are detected; skips pinning on single-node or VM systems |
| Free disk space | Warns before SF100 if < 200 GB available |

The scripts print a full summary of computed parameters before starting. Generated `postgresql.conf` and TCL files are written to a temp directory and cleaned up on exit. The static files under `docker/` and `tcl/` remain useful as reference configs for manual runs on the reference system.

---

## TPC-C (OLTP)

### What it measures
New Orders Per Minute (NOPM) — a mix of 5 transaction types (New Order, Payment, Order Status, Delivery, Stock Level). Higher is better.

### Auto-scaled parameters (reference system: 377 GB RAM, 32 bench CPUs)
| Parameter | Formula | Reference value |
|-----------|---------|-----------------|
| `shared_buffers` | 25% RAM, max 80 GB | 80 GB |
| `work_mem` | 4 MB × RAM(GB), max 2 GB | 512 MB |
| `synchronous_commit` | off (always) | off |
| `jit` | off (always) | off |
| Warehouses | 4 × run VUs, min 64 | 64 |
| Build VUs | CPUs/8, min 4, max 16 | 4 |
| Run VUs | CPUs/2, min 8, max 64 | 16 |
| Ramp-up / Timed run | fixed | 2 min / 10 min |

### Quickstart
```bash
HAMMERDB_DIR=/path/to/HammerDB ./run_tpcc.sh
```

### Manual step-by-step

**1. Start the container**
```bash
docker rm -f pg-tpcc 2>/dev/null || true
docker run -d \
  --name pg-tpcc \
  --shm-size=4g \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v pg-tpcc-data:/var/lib/postgresql/data \
  -v "$PWD/docker/tpcc/postgresql.conf:/etc/postgresql/postgresql.conf:ro" \
  postgres:17 \
  postgres -c config_file=/etc/postgresql/postgresql.conf

until docker exec pg-tpcc pg_isready -U postgres -q; do sleep 2; done
echo "Ready"
```

> **NUMA pinning** (optional, multi-socket/NPS systems): add `--cpuset-cpus "0-15,64-79" --cpuset-mems 0` to pin to NUMA node 0. The automated script does this automatically when multiple NUMA nodes are detected.

**2. Verify config**
```bash
docker exec pg-tpcc psql -U postgres -c \
  "SHOW shared_buffers; SHOW jit; SHOW synchronous_commit;"
```

**3. Build schema** (~15-25 minutes)
```bash
cd $HAMMERDB_DIR
TMP=/tmp ./hammerdbcli auto /path/to/postgresql-bench/tcl/tpcc/tpcc_build.tcl 2>&1 | tee tpcc_build.log
```

**4. Run benchmark** (~12 minutes)
```bash
TMP=/tmp ./hammerdbcli auto /path/to/postgresql-bench/tcl/tpcc/tpcc_run_32vu.tcl 2>&1 | tee tpcc_run.log
```

**5. Read results**
HammerDB prints NOPM and TPM at the end of the run. Look for:
```
Vuser 1:TEST RESULT : System achieved NNNN NOPM from NNNN PostgreSQL TPM
```

### TPC-C Results

| Run | VUs | Warehouses | NOPM | TPM |
|-----|-----|------------|------|-----|
| PostgreSQL 17, NPS4 node0 (CPUs 0-15,64-79), `synchronous_commit=off`, `jit=off`, `shared_buffers=80GB` | 32 | 64 | **973,227** | **2,240,247** |

---

## TPC-H (OLAP)

### What it measures
Query-per-hour H-Scoring (QphH) — 22 complex analytical queries over a large dataset. Higher is better.

### Scale factors
| Scale | Raw data | Load time | Disk needed | Use case |
|-------|----------|-----------|-------------|----------|
| SF10  | ~10 GB   | 15-30 min | ~20 GB | Validation / quick run |
| SF100 | ~100 GB  | 2-4 hours | ~200 GB | Production benchmark |

### Auto-scaled parameters (reference system: 377 GB RAM, 32 bench CPUs)
| Parameter | Formula | Reference value |
|-----------|---------|-----------------|
| `shared_buffers` | 40% RAM | 150 GB |
| `work_mem` | `(85%RAM − SB) / (thru_vus × (dop+1))`, max 8 GB | 8 GB |
| `jit` | on (always) | on |
| `autovacuum` | off (always) | off |
| `wal_level` | minimal (always) | minimal |
| Build threads | min(CPUs, 16) | 16 |
| Power test dop | CPUs/4, max 16 | 8 |
| Throughput VUs | CPUs/8, min 2, max 10 | 4 |
| Throughput dop | CPUs/(VUs×2), max 8 | 4 |

### Quickstart
```bash
HAMMERDB_DIR=/path/to/HammerDB ./run_tpch.sh sf10    # validation
HAMMERDB_DIR=/path/to/HammerDB ./run_tpch.sh sf100   # production benchmark
```

### Manual step-by-step

**1. Start the container**
```bash
docker rm -f pg-tpch 2>/dev/null || true
docker run -d \
  --name pg-tpch \
  --shm-size=100g \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v pg-tpch-sf10-data:/var/lib/postgresql/data \
  -v "$PWD/docker/tpch/postgresql.conf:/etc/postgresql/postgresql.conf:ro" \
  postgres:17 \
  postgres -c config_file=/etc/postgresql/postgresql.conf

until docker exec pg-tpch pg_isready -U postgres -q; do sleep 2; done
```

> **NUMA pinning** (optional): add `--cpuset-cpus "0-15,64-79" --cpuset-mems 0` for NPS4/multi-socket systems. Adjust `--shm-size` to match `shared_buffers`.

**2. Build schema** (SF10: 15-30 min / SF100: 2-4 hours)
```bash
# SF10 (validation)
TMP=/tmp ./hammerdbcli auto /path/to/postgresql-bench/tcl/tpch/tpch_build_sf10.tcl 2>&1 | tee tpch_build_sf10.log

# SF100 (production)
TMP=/tmp ./hammerdbcli auto /path/to/postgresql-bench/tcl/tpch/tpch_build_sf100.tcl 2>&1 | tee tpch_build_sf100.log
```

**3. Power test** (1 VU, all 22 queries once)
```bash
TMP=/tmp ./hammerdbcli auto /path/to/postgresql-bench/tcl/tpch/tpch_power_sf10.tcl 2>&1 | tee tpch_power_sf10.log
```

**4. Throughput test** (multiple VUs concurrently)
```bash
TMP=/tmp ./hammerdbcli auto /path/to/postgresql-bench/tcl/tpch/tpch_throughput_sf10.tcl 2>&1 | tee tpch_throughput_sf10.log
```

### TPC-H Results

PostgreSQL 17, NPS4 node0 CPUs (0-15,64-79), `shared_buffers=100GB`, `work_mem=4GB`, `jit=on`

| Scale | Test | Queries | Total Time | Geo Mean Query Time | Notes |
|-------|------|---------|------------|---------------------|-------|
| SF10  | Power      | 22      | 78 s     | 1.88 s  | 1 VU, dop=8 |
| SF10  | Throughput | 22×5    | ~105 s   | 2.75 s  | 5 VUs, dop=3 |
| SF100 | Power      | 22      | 879 s    | 23.4 s  | 1 VU, dop=8 — Power@SF100 = **15,375** |
| SF100 | Throughput | 22×5    | 1,631 s  | 42.9 s  | 5 VUs, dop=3 — Throughput@SF100 = **24,280** |

**QphH@SF100 = √(15,375 × 24,280) = 19,321**

#### SF100 Power test — per-query times

| Query | Time (s) | Query | Time (s) | Query | Time (s) |
|-------|----------|-------|----------|-------|----------|
| Q1  | 33.2  | Q9  | 50.1  | Q17 | 102.6 |
| Q2  | 28.8  | Q10 | 32.7  | Q18 | 92.6  |
| Q3  | 36.1  | Q11 | 7.1   | Q19 | 2.1   |
| Q4  | 6.5   | Q12 | 12.0  | Q20 | 53.9  |
| Q5  | 18.8  | Q13 | 138.2 | Q21 | 20.5  |
| Q6  | 7.4   | Q14 | 117.8 | Q22 | 2.1   |
| Q7  | 14.0  | Q15 | 47.2  |     |       |
| Q8  | 15.7  | Q16 | 39.9  |     |       |

#### Comparison with Viettel PoC reference

| System | CPU | QphH@SF100 |
|--------|-----|------------|
| This run | AMD EPYC 9555P (1S, NPS4 node0, 32 logical CPUs) | **19,321** |
| Viettel PoC reference | AMD EPYC 9454 | 14,644 |

The EPYC 9555P result is **32% higher** than the Viettel PoC reference on the EPYC 9454.

---

## Repository Structure

```
postgresql-bench/
├── docker/
│   ├── tpcc/postgresql.conf      # OLTP-tuned PostgreSQL config
│   └── tpch/postgresql.conf      # OLAP-tuned PostgreSQL config
├── tcl/
│   ├── tpcc/
│   │   ├── tpcc_build.tcl        # Build TPC-C schema (64W, 8 VUs)
│   │   └── tpcc_run_32vu.tcl     # Run TPC-C (32 VUs, 2m+10m)
│   └── tpch/
│       ├── tpch_build_sf10.tcl   # Build TPC-H schema (SF10)
│       ├── tpch_build_sf100.tcl  # Build TPC-H schema (SF100)
│       ├── tpch_power_sf10.tcl   # Power test (SF10)
│       ├── tpch_power_sf100.tcl  # Power test (SF100)
│       ├── tpch_throughput_sf10.tcl
│       └── tpch_throughput_sf100.tcl
├── results/
│   ├── tpcc/                     # TPC-C run logs
│   └── tpch/                     # TPC-H run logs
├── run_tpcc.sh                   # Automated TPC-C runner
├── run_tpch.sh                   # Automated TPC-H runner (arg: sf10|sf100)
└── README.md
```

---

## Tuning Notes

### Why `synchronous_commit = off` for TPC-C?
Each transaction waits for WAL to flush before acknowledging the client. Disabling this allows the WAL writer to batch flushes, dramatically improving throughput. Data is not lost on PostgreSQL crash (WAL is still written) but could be lost on OS crash. Acceptable for benchmarking.

### Why `jit = off` for TPC-C?
JIT compilation adds latency for short OLTP transactions — the compilation overhead exceeds the execution savings. For TPC-H (long-running analytical queries), JIT is enabled.

### Why large `shared_buffers` for TPC-H?
With SF100, the working set is ~100+ GB. Setting `shared_buffers` to 40% of RAM means most of the dataset fits in the buffer pool after the first scan, eliminating repeated disk I/O. The automated script caps this at a level that leaves enough room for `work_mem × parallel streams` to avoid OOM.

### Why `--cpuset-mems 0`?
On NPS4, each NUMA node has its own memory controller. Without this flag, PostgreSQL will allocate memory from all 4 nodes, causing cross-NUMA memory access latency (~12 cycles vs ~10 cycles local). Pinning memory to node0 ensures all allocations are local to the CPUs we're using.

### Why `huge_pages = try`?
2 MB huge pages reduce TLB pressure significantly for large `shared_buffers`. If the OS has huge pages enabled (`/proc/sys/vm/nr_hugepages`), PostgreSQL will use them; otherwise falls back to normal pages without error.

```bash
# Enable huge pages (optional, requires root)
# For 80GB shared_buffers: 80*1024/2 = 40960 pages
sudo sysctl -w vm.nr_hugepages=40960
```

---

## Cleanup

```bash
# Stop and remove containers
docker rm -f pg-tpcc pg-tpch

# Remove data volumes (destructive — schema must be rebuilt)
docker volume rm pg-tpcc-data pg-tpch-sf10-data pg-tpch-sf100-data
```
