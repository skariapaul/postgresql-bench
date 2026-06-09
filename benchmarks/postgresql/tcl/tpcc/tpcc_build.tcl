#!/bin/tclsh
# TPC-C schema build — 64 warehouses, 8 build VUs
# Target: PostgreSQL at localhost:5432

puts "SETTING CONFIGURATION"
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
diset tpcc pg_count_ware 64
diset tpcc pg_num_vu 8
diset tpcc pg_allwarehouse true
diset tpcc pg_partition false
diset tpcc pg_storedprocs true
diset tpcc pg_vacuum true

puts "SCHEMA BUILD STARTED"
buildschema
puts "SCHEMA BUILD COMPLETED"
