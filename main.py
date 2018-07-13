import hashlib
import random
import threading
import coloredlogs
import logging
from queue import Queue

nr_threads = 10
max_randint = 10000000000
nonce_max_jump = 1000
difficulty = 4
genesis= "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
genesis = genesis[:-difficulty] + "0" * difficulty


# TODO: Use https://github.com/Tierion/pymerkletools ? Has pure data implement?

def hasher(content):
        return hashlib.sha256(content.encode()).hexdigest()


# Return empty string if content is None
def xstr(s):
    return '' if s is None else str(s)


def mine(content=None):
    nonce = random.randrange(max_randint)
    while True:
        hashed = hasher(xstr(content)+str(nonce))
        if hashed[-difficulty:] == "0" * difficulty:
            break
        nonce += random.randrange(nonce_max_jump)
    return hashed


def get_blockstring(block):
    return str(list(block.queue)[0])


def verifier():
    while True:
        pass


def spawn(amount, worker):
    threads = []
    for i in range(amount):
        t = threading.Thread(name='verifier_' + str(i), target=worker)
        threads.append(t)

        t.start()
    return threads


logger = logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger,
                    fmt='(%(threadName)-10s) %(message)s')

q = Queue()
last_block = Queue()

# Threadsafe genesis block
last_block.put(genesis)

verifier_threads = spawn(amount=nr_threads, worker=verifier)
