#!/bin/bash

SECRET="testing"
RPS=500
TOTAL=30000
IMSI_BASE=268010000000001
INSTANCES=10

for i in $(seq 0 $((INSTANCES - 1))); do
    IMSI=$((IMSI_BASE + i * TOTAL))
    echo "Instance $i — imsi=$IMSI rps=$RPS total=$TOTAL"
    python3 radius_load.py --secret $SECRET --rps $RPS --total $TOTAL --imsi $IMSI &
done

wait
echo "All done — total sent: $((INSTANCES * TOTAL)) requests @ $((INSTANCES * RPS)) rps"
