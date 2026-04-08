# this is a worker.
# this is the thing that's responsible for
# taking in a benchmark, processing it somehow, etc.
# it should have some functions like: 
# start the trial in the docker image
# clean up everything in the docker image, etc.
# this is going to be the meat of the whole thing
# i think it's basically going to replace the old 'vectorizer.py'
# function i had earlier

# consider making this an abstract class, and making workers that
# inherit from it per experiment

# so, we would have a different worker for the rust experiments
# than the workers for the vectorization experiments
