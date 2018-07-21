import hashlib
import random
import threading
import coloredlogs
import logging
import time
from queue import Queue
from pki import get_kp
from random import randint

top_level_peers = 5  # tlp
branch_factor = 2  # bf

highest_level_simulation_factor = 5  # hlsf

# Geometric series = [tlp, tlp*bf, tlp*bf^2, ..... , tlp*bf^hlsf]
level_progression = [top_level_peers * branch_factor**i for i in
                     range(highest_level_simulation_factor)]

levels_list = []
counter = 0
for level in level_progression:
    for thread in range(level):
        levels_list.append(counter)
    counter = counter + 1

nr_threads = 30

levels_list = levels_list[:nr_threads]

max_randint = 10000000000
nonce_max_jump = 1000
difficulty = 3
genesis = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
genesis = genesis[:-difficulty] + "0" * difficulty


def hasher(content):
        return hashlib.sha256(content.encode()).hexdigest()


# Return empty string if content is None
def xstr(s):
    return '' if s is None else str(s)


def similar(a, b):
    a_to_int = int(a, 16)
    b_to_int = int(b, 16)
    diff = abs(a_to_int - b_to_int)

    max_possible = int(pow(16, 64)) - 1

    fraction = diff/max_possible

    return fraction, a_to_int/max_possible, b_to_int/max_possible


def mine(content=None):
    nonce = random.randrange(max_randint)
    while True:
        hashed = hasher(xstr(content)+str(nonce))
        if hashed[-difficulty:] == "0" * difficulty:
            break
        nonce += random.randrange(nonce_max_jump)
    return hashed


def verifier(i, ranked_list):
    my_pubkey, my_level = ranked_list[i]
    wait_for_new_tick = False

    if my_level == 0:
        current_block = last_block()

        while True:
            if wait_for_new_tick:
                time.sleep(0.2)
                check_block = last_block()

                if current_block != check_block:  # Tick was put so continue
                    wait_for_new_tick = False
                    current_block = check_block

            else:
                top_peers = ranked_list[:top_level_peers]

                # Used to use | hash(pubk) - hash(ref) |, but this gave too low
                # randomness. so now using | hash(pubk+ref) - hash(ref) |
                similarity_list = \
                    [similar(hasher(peers_pubkey+current_block), current_block)
                     for peers_pubkey, _ in top_peers]

                score, pubk_score, block_score = similarity_list[i]

                logger.info(
                    "I am " + str(my_pubkey) + " my score is "
                    + str(round(score, 3)) + " (|" + str(round(pubk_score, 3))
                    + " - " + str(round(block_score, 3)) + "|)")

                indices = sorted(range(len(similarity_list)),
                                 key=lambda k: similarity_list[k][0],
                                 reverse=True)

                # Get peers ranked in descending order of score
                peer_whos_turn_it_is, _ = top_peers[indices[0]]
                if my_pubkey == peer_whos_turn_it_is:
                    new_hash = mine()

                    # Hash an extra time to avoid same peer with lucky zeros at
                    # the end to win every time.....
                    new_hash = hasher(new_hash)
                    logger.critical("Put " + new_hash)
                    time.sleep(5)  # Simulate some extra difficulty..
                    chain.put(new_hash)

                wait_for_new_tick = True

    else:
        # TODO: Implemented branching factor and transactions
        pass


def last_block():
    return list(chain.queue)[-1]


def spawn(amount, worker, ranked_list):
    threads = []
    for i in range(amount):
        t = threading.Thread(name='verifier_' + str(i), target=worker,
                             args=(i, ranked_list,))
        threads.append(t)
        t.start()
    return threads


logger = logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger,
                    fmt='%(asctime)s (%(threadName)-10s) %(message)s')


chain = Queue()
chain.put(genesis)

# Create simulated hierarchical list of peers, as if gotten from tempus network
peerdict = {}
for peer in range(nr_threads):
    pubkey = get_kp()[0][:64]  # Truncated to be comparable to hashes

    random_score = randint(0, nr_threads)

    peerdict[pubkey] = random_score

peerdict_sorted = sorted(peerdict, key=peerdict.get, reverse=True)

# Calculate levels of peers
levels = []
for idx, peer in enumerate(peerdict_sorted):
    levels.append((peer, levels_list[idx]))

verifier_threads = spawn(amount=nr_threads, worker=verifier, ranked_list=levels)
