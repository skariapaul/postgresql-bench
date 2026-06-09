# Benchmarks

Reproducible database benchmarks on bare-metal hardware. Each subdirectory contains a self-contained benchmark suite with scripts, configs, and results.

## System

AMD EPYC 9555P — 64 cores / 128 threads, single socket, NPS4, 377 GiB DDR5, 465 GB NVMe SSD, Ubuntu 24.04 LTS.

## Benchmarks

| Directory | Database | Workloads | Latest results |
|-----------|----------|-----------|----------------|
| [postgresql/](benchmarks/postgresql/) | PostgreSQL 17 | TPC-C (OLTP), TPC-H (OLAP) SF10 & SF100 | TPC-C: **973,227 NOPM** · TPC-H SF100: **QphH 19,321** |

## Adding a benchmark

Create a new subdirectory under `benchmarks/` with its own `README.md`, runner scripts, and config files following the same pattern as the PostgreSQL benchmark.
