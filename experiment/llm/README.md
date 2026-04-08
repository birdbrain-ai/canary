### Usage notes

The execution order is:

1. Build the Apptainer image:

./build.sh


2. Launch the vLLM server:

sbatch serve.sh 8000

Monitor job progress with:

tail -f [job_id]-serve.sh.out


3. Port forward to the access node:

sbatch portforward.sh 8000

Then, check the allocated port:

cat [job_id]-portforward.sh.out


4. Test query:

./test_query.sh [port]

