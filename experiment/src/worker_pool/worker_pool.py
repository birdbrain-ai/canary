# this class is a worker pool. what it contains, hard to say! probably just a queue of workers
# this is basically going to look like a regular process/thread pool. idk if python has a library
# to manage that though

# This does need to exist. Unfortunately, since a Worker is way more than just a Thread / Process,
# We need to create a WorkerPool that contains either a Thread or ProcessPoolExecutor
