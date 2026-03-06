while true; do
    ssh -L 8000:erebus:8000 \
        -o ServerAliveInterval=60 \
        -o ServerAliveCountMax=3 \
        -N jtm2066@slurm01.cs.northwestern.edu
    echo "Tunnel died, restarting in 5s..."
    sleep 5
done
