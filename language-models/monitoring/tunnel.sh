#!/usr/bin/env bash
while true; do
    echo "Starting tunnel"
    sshpass -p 'howdyboss' ssh \
            -L 0.0.0.0:8000:localhost:8000 \
            -o ProxyCommand="sshpass -p 'howdyboss' ssh -W %h:%p jtm2066@slurm01.cs.northwestern.edu" \
            -o StrictHostKeyChecking=no \
            jtm2066@erebus \
            -N
    echo "Tunnel died, restarting in 5s..."
    sleep 5
done
