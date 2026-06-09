#!/bin/tclsh
# TPC-C timed run — 32 VUs, 2 min ramp-up, 10 min timed
# Target: PostgreSQL at localhost:5432

set tmpdir $::env(TMP)
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
diset tpcc pg_driver timed
diset tpcc pg_rampup 2
diset tpcc pg_duration 10
diset tpcc pg_allwarehouse true
diset tpcc pg_vacuum true
diset tpcc pg_timeprofile true
diset tpcc pg_total_iterations 10000000

loadscript
puts "TEST STARTED"
vuset vu 32
vuset logtotemp 1
vucreate
set jobid [ vurun ]
vudestroy
puts "TEST COMPLETE"
set of [ open $tmpdir/pg_tprocc w ]
puts $of $jobid
close $of
