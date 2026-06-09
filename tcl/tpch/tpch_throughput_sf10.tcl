#!/bin/tclsh
# TPC-H throughput test — SF10, 5 VUs, degree_of_parallel 3
# Runs all 22 queries concurrently across 5 virtual users.

set tmpdir $::env(TMP)
puts "SETTING CONFIGURATION"
dbset db pg
dbset bm TPC-H

diset connection pg_host localhost
diset connection pg_port 5432
diset connection pg_sslmode prefer

diset tpch pg_scale_fact 10
diset tpch pg_tpch_user tpch
diset tpch pg_tpch_pass tpch
diset tpch pg_tpch_dbase tpch
diset tpch pg_total_querysets 1
diset tpch pg_degree_of_parallel 3

loadscript
puts "TEST STARTED"
vuset vu 5
vuset logtotemp 1
vucreate
set jobid [ vurun ]
vudestroy
puts "TEST COMPLETE"
set of [ open $tmpdir/pg_tproch_throughput w ]
puts $of $jobid
close $of
