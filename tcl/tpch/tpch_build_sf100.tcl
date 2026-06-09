#!/bin/tclsh
# TPC-H schema build — Scale Factor 100 (≈100 GB raw data)
# Expect 1-2 hours to complete on NVMe. Requires ~150 GB free disk.
# Target: PostgreSQL at localhost:5432

puts "SETTING CONFIGURATION"
dbset db pg
dbset bm TPC-H

diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer

diset tpch pg_scale_fact 100
diset tpch pg_num_tpch_threads 10
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
