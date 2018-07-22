import hashlib
import random
import threading
import coloredlogs
import logging
import time
import sys
from datetime import datetime
import pytz
from flask import Flask, jsonify
from queue import Queue
from pki import get_kp
from random import randint

top_level_peers = 5  # tlp
branch_factor = 2  # bf

highest_level_simulation_factor = 4  # hlsf

nr_threads = 75

max_randint = 10000000000

txn_probability = 0.1

sleeping_time = 0
nonce_max_jump = 1000
difficulty = 2
genesis = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
genesis = genesis[:-difficulty] + "0" * difficulty
genesis_item = {genesis: []}


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


def last_block():
    return next(iter(list(chain.queue)[-1]))


def count(list_of_items):
    cnt = 0
    for item in list_of_items:
        if isinstance(item, dict):
            for list_of_items in item.values():
                # If list is nested further, and is a list
                if list_of_items and isinstance(list_of_items, list):
                    cnt += count(list_of_items)
                else:  # If list is empty
                    cnt += 1
    return cnt


def mine(content=None):
    nonce = random.randrange(max_randint)
    while True:
        hashed = hasher(xstr(content)+str(nonce))
        if hashed[-difficulty:] == "0" * difficulty:
            break
        nonce += random.randrange(nonce_max_jump)
    return hashed


def messages(my_pubkey):
    inbox_list = list(inbox[my_pubkey].queue)
    return inbox_list


def total_messages():
    return sum([queue.qsize() for queue in inbox.values()])


def print_status(my_pubkey, score, log_type):
    log_type("I am " + str(my_pubkey)[:6] + ", score: " + str(round(score, 3)))


def mine_and_alert(my_pubkey, my_level):
    contents = messages(my_pubkey)
    new_hash = mine(contents)
    # logger.info("Mined " + str(messages(my_pubkey)) + " at level "
    # + str(my_level) + " became " + str(new_hash))

    return new_hash, contents


# Global methods
def utcnow():
    return int(datetime.now(tz=pytz.utc).timestamp())


def clear_inbox(my_pubkey):
    with inbox[my_pubkey].mutex:
        inbox[my_pubkey].queue.clear()


def wait_for_full_inbox(my_pubkey):
    while len(messages(my_pubkey)) < branch_factor:
        time.sleep(0.2)


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
                        logger.info("------------------- " + str(chain.qsize())
                                    + ", txn: " + str(count(list(chain.queue)))
                                    + ", waiting txn: " + str(total_messages()))
                    else:
                        time.sleep(0.5)

                    wait_for_new_tick = False
                    current_block = check_block

            else:

                # Calculate similarity score to prev_hash for each top peer
                # => Consensus mechanism to lottery determine next block forger
                similarity_list = []
                for peers_pubkey in top_peers:
                    pubkhash = hasher(peers_pubkey+current_block)

                    # Hash current_block extra time to avoid same peer with
                    # lucky zeros at the end to win every time.....
                    prevhash = hasher(current_block)

                    # Used to use | hash(pubk) - hash(ref) |, but this gave too
                    # low randomness so now using | hash(pubk+ref) - hash(ref) |
                    similarity = similar(pubkhash, prevhash)
                    similarity_list.append(similarity)

                score = similarity_list[i]

                indices = sorted(range(len(similarity_list)),
                                 key=lambda k: similarity_list[k],
                                 reverse=True)

                # Get peers ranked in descending order of score
                peer_whos_turn_it_is = top_peers[indices[0]]

                # TODO: Simulate failure rate in putting within 5 sec window
                if my_pubkey == peer_whos_turn_it_is:
                    wait_for_full_inbox(my_pubkey)

                    new_hash, content = mine_and_alert(my_pubkey, my_level)

                    block = {new_hash: content, "ts": utcnow()}

                    print_status(my_pubkey, score, logger.critical)

                    time.sleep(sleeping_time)  # Simulate some extra difficulty

                    chain.put(block)
                else:
                    print_status(my_pubkey, score, logger.info)

                clear_inbox(my_pubkey)

                wait_for_new_tick = True

    else:
        # For all other levels that are not level 0
        while True:
            if random.random() < txn_probability:

                peers_above_me = peers_at_level[my_level - 1]

                if my_level + 2 > len(peers_at_level):
                    peers_below_me = False  # In this case there is no list
                else:
                    # Here list exists but could be empty [] or have items
                    peers_below_me = peers_at_level[my_level + 1]

                if peers_below_me:  # Leaf node if this is either [] or False
                    wait_for_full_inbox(my_pubkey)

                my_txn, content = mine_and_alert(my_pubkey, my_level)

                item = {my_txn: content, "ts": utcnow()}

                inbox[random.choice(peers_above_me)].put(item)

                clear_inbox(my_pubkey)

                time.sleep(2)


def spawn(amount, worker):
    threads = []
    for i in range(amount):
        t = threading.Thread(name='verifier_' + str(i), target=worker,
                             args=(i,))
        threads.append(t)
        t.start()
    return threads


app = Flask(__name__)


# API for inspecting state of chain/program etc via web API
@app.route('/chain')
def chain():
    return jsonify(list(chain.queue))


if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    coloredlogs.install(level='DEBUG', logger=logger,
                        fmt='%(asctime)s (%(threadName)-10s) %(message)s')

    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    chain = Queue()
    chain.put(genesis_item)

    # Create simulated hierarchical list of peers, as gotten from tempus network
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

    if sum(level_progression) < nr_threads:
        sys.exit("Too many threads (" + str(nr_threads)
                 + ") for total in level progression. Decrease #threads to <= "
                 + str(sum(level_progression)))

    # A list of corresponding levels for peers: [0,0, 1,1,1,1, ...... , n, n]
    levels_list = []
    counter = 0
    for level in level_progression:
        for thread in range(level):
            levels_list.append(counter)
        counter = counter + 1
    levels_list = levels_list[:nr_threads]  # Chomp off at end

    # Initializing a container: list of lists containing peers at diff levels
    peers_at_level = [[] for i in range(highest_level_simulation_factor)]

    # Initializing personal messaging queues for each thread
    inbox = {}

    # Initializing ranked levels list containing tuples of (peer, level)
    peer_ranked_list = []

    for idx, peer in enumerate(peerdict_sorted):
        peer_ranked_list.append((peer, levels_list[idx]))

        # This is to get a list of all peers at lvl X: peers_at_level[X]
        peers_at_level[levels_list[idx]].append(peer)

        # This is to reach inbox of each peer: inbox[peer].put(message)
        inbox[peer] = Queue()

    verifier_threads = spawn(amount=nr_threads, worker=verifier)

    info = "["
    for idx, level in enumerate(level_progression):
        if idx < len(peers_at_level):
            nr_peers = len(peers_at_level[idx])

            info += str(nr_peers) + "/" + str(level) + ", "
    info += "]"
    logger.debug("Level progressions: " + info)

    app.run(debug=False)
