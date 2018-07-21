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

nr_threads = 30

max_randint = 10000000000

every_nth_txneer = 10

nonce_max_jump = 1000
difficulty = 2
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
    distance = abs(a_to_int - b_to_int)

    max_possible = int(pow(16, 64)) - 1

    fraction = distance/max_possible

    return fraction


def mine(content=None):
    nonce = random.randrange(max_randint)
    while True:
        hashed = hasher(xstr(content)+str(nonce))
        if hashed[-difficulty:] == "0" * difficulty:
            break
        nonce += random.randrange(nonce_max_jump)
    return hashed


def messages(my_pubkey):
    return list(inbox[my_pubkey].queue)


def print_status(my_pubkey, score, log_type):
    log_type("I am " + str(my_pubkey)[:6] + ", score: " + str(round(score, 3)))


def verifier(i):
    my_pubkey, my_level = peer_ranked_list[i]
    wait_for_new_tick = False

    top_peers = peers_at_level[0]
    current_block = last_block()

    if my_level == 0:
        while True:
            if wait_for_new_tick:
                time.sleep(0.2)
                check_block = last_block()

                if current_block != check_block:  # Tick was put so continue

                    # Visual divider
                    if i % top_level_peers == 0:
                        logger.info("--------------------------------")
                    else:
                        time.sleep(0.5)

                    wait_for_new_tick = False
                    current_block = check_block

            else:
                # Used to use | hash(pubk) - hash(ref) |, but this gave too low
                # randomness. so now using | hash(pubk+ref) - hash(ref) |
                similarity_list = \
                    [similar(hasher(peers_pubkey+current_block), current_block)
                     for peers_pubkey in top_peers]

                score = similarity_list[i]

                indices = sorted(range(len(similarity_list)),
                                 key=lambda k: similarity_list[k],
                                 reverse=True)

                # Get peers ranked in descending order of score
                peer_whos_turn_it_is = top_peers[indices[0]]

                # TODO: Simulate failure rate in putting within 5 sec window
                if my_pubkey == peer_whos_turn_it_is:
                    logger.info("Gonna mine " + str(messages(my_pubkey)))
                    new_hash = mine(messages(my_pubkey))

                    # Hash an extra time to avoid same peer with lucky zeros at
                    # the end to win every time.....
                    new_hash = hasher(new_hash)

                    print_status(my_pubkey, score, logger.critical)

                    time.sleep(5)  # Simulate some extra difficulty..

                    chain.put(new_hash)
                else:
                    print_status(my_pubkey, score, logger.info)

                with inbox[my_pubkey].mutex:
                    inbox[my_pubkey].queue.clear()

                wait_for_new_tick = True

    else:
        # For all other levels that are not level 0
        if my_level == 1:
            while True:
                if wait_for_new_tick:
                    time.sleep(0.2)
                    check_block = last_block()
                    if current_block != check_block:  # Tick was put so continue
                        wait_for_new_tick = False
                        current_block = check_block

                else:
                    # One in every_nth_txneer chance of making a txn
                    make_txn = \
                        randint(0, every_nth_txneer) % every_nth_txneer == 0

                    if make_txn:
                        my_txn = mine()
                        peers_above_me = peers_at_level[my_level - 1]
                        for peer_above in peers_above_me:
                            inbox[peer_above].put(my_txn)

                    wait_for_new_tick = True


def last_block():
    return list(chain.queue)[-1]


def spawn(amount, worker):
    threads = []
    for i in range(amount):
        t = threading.Thread(name='verifier_' + str(i), target=worker,
                             args=(i,))
        threads.append(t)
        t.start()
    return threads


logger = logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger,
                    fmt='%(asctime)s (%(threadName)-10s) %(message)s')

chain = Queue()
chain.put(genesis)

# Create simulated hierarchical list of peers, as if gotten from tempus network
peer_dict = {}
for peer in range(nr_threads):
    pubkey = get_kp()[0]

    random_score = randint(0, nr_threads)

    peer_dict[pubkey] = random_score

peerdict_sorted = sorted(peer_dict, key=peer_dict.get, reverse=True)

# Generate level progression with a geometric series using constants
# Geometric series = [tlp, tlp*bf, tlp*bf^2, ..... , tlp*bf^hlsf]
level_progression = [top_level_peers * branch_factor**i for i in
                     range(highest_level_simulation_factor)]

# A list of corresponding levels for each peer: [0,0, 1,1,1,1, ...... , n, n]
levels_list = []
counter = 0
for level in level_progression:
    for thread in range(level):
        levels_list.append(counter)
    counter = counter + 1
levels_list = levels_list[:nr_threads]  # Chomp off at end

# Initializing a container: list of lists containing peers at different levels
peers_at_level = [[] for i in range(highest_level_simulation_factor)]

# Initializing personal messaging queues for each thread
inbox = {}

# Initializing ranked levels list containing tuples of (peer, level)
peer_ranked_list = []

for idx, peer in enumerate(peerdict_sorted):
    peer_ranked_list.append((peer, levels_list[idx]))

    # This is to be able to get a list of all peers at lvl X: peers_at_level[X]
    peers_at_level[levels_list[idx]].append(peer)

    # This is to be able to reach inbox of each peer: inbox[peer].put(message)
    inbox[peer] = Queue()

verifier_threads = spawn(amount=nr_threads, worker=verifier)
