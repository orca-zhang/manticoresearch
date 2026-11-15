#!/bin/sh
set -u
taskdir=/media/SSD-Storage1/manticore-reader-tls-20261114/idle-20261114
restore_services() {
    date -u > "$taskdir/service-restore-started-20261115.txt"
    restore_rc=0
    systemctl start zimaos-search.service || restore_rc=$?
    systemctl start zimaos-photos.service || restore_rc=$?
    systemctl show zimaos-search.service zimaos-photos.service -p Id -p ActiveState -p SubState -p MainPID > "$taskdir/service-after-20261115.log"
    printf '%s\n' "$restore_rc" > "$taskdir/service-restore-exit-code.txt"
}
trap restore_services 0
trap 'exit 130' INT
trap 'exit 143' TERM HUP
date -u > "$taskdir/service-stop-started-20261115.txt"
systemctl show zimaos-search.service zimaos-photos.service -p Id -p ActiveState -p SubState -p MainPID > "$taskdir/service-before-benchmark-20261115.log"
systemctl stop zimaos-search.service || exit 1
systemctl stop zimaos-photos.service || exit 1
date -u > "$taskdir/services-stopped-20261115.txt"
docker exec manticore-reader-tls-20261114 python3 /work/idle-20261114/run_idle.py > "$taskdir/logs/orchestration-20261115.log" 2>&1
bench_rc=$?
printf '%s\n' "$bench_rc" > "$taskdir/benchmark-exit-code.txt"
exit "$bench_rc"
