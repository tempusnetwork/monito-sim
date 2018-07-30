import hashlib
import random
import threading
import coloredlogs
import logging
import time
from datetime import datetime
import pytz
from flask import Flask, jsonify
from queue import Queue
from pki import get_kp
from random import randint

top_level_peers = 5  # tlp
branch_factor = 2  # bf

nr_threads = 30

max_randint = 10000000000

txn_probability = 0.05

artificial_network_latency = 2

nonce_max_jump = 1000
difficulty = 2
genesis_hash = \
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
genesis_hash = genesis_hash[:-difficulty] + "0" * difficulty


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
    return list(chain.queue)[-1]


# Counts various statistics about blocks
def count(list_of_items):
    txn_cnt = 0
    ts_total = 0
    for item in list_of_items:
        if isinstance(item, dict):
            for key in item.keys():
                # If list is nested further, and is a list
                if key == "c":  # Content
                    if item["c"]:
                        to_add_txn_cnt, to_add_ts_total = count(item["c"])
                        txn_cnt += to_add_txn_cnt
                        ts_total += to_add_ts_total
                    else:  # If list is empty
                        txn_cnt += 1
                        ts_total += item["ts"]

    return txn_cnt, ts_total


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


def total_waiting_messages():
    return sum([queue.qsize() for queue in inbox.values()])


def print_status(my_pubkey, score, log_type):
    log_type("I am " + str(my_pubkey)[:6] + ", score: " + str(round(score, 3)))


def utcnow():
    return int(datetime.now(tz=pytz.utc).timestamp())


def clear_inbox(my_pubkey):
    with inbox[my_pubkey].mutex:
        inbox[my_pubkey].queue.clear()


def wait_for_full_inbox(my_pubkey):
    while len(messages(my_pubkey)) < branch_factor:
        time.sleep(0.2)


def construct_block(block_hash, content, timestamp):
    return {"h": block_hash, "c": content, "ts": timestamp}


# Calculate similarity score to prev_hash for each top peer
# => Consensus mechanism to determine next block forger via lottery
def get_sim_dict(top_peers, current_block_hash):
    similarity_dict = {}
    for peers_pubkey in top_peers:
        pubkhash = hasher(peers_pubkey + current_block_hash)

        # Hash current_block extra time to avoid same peer with
        # lucky zeros at the end to win every time.....
        prevhash = hasher(current_block_hash)

        # Used to use | hash(pubk) - hash(ref) |, but this gave too
        # low randomness so now using | hash(pubk+ref) - hash(ref) |
        similarity = similar(pubkhash, prevhash)
        similarity_dict[peers_pubkey] = similarity
    return similarity_dict


def block_info():
    latest_block = last_block()

    # Listifying latest_block to aid recursion of count function
    nr_txn_added, leaf_timestamps_sum = count([latest_block])

    block_timestamp = latest_block["ts"]
    avg_leaf_timestamp = leaf_timestamps_sum / nr_txn_added

    # TODO: Also measure longest wait? Variance? Distribution?
    avg_wait = block_timestamp - avg_leaf_timestamp

    logger.info("--------------- block " + str(chain.qsize())
                + ", added txn: " + str(nr_txn_added)
                + ", avg wait: " + str(round(avg_wait, 3))
                + "s, waiting txn: " + str(total_waiting_messages()))


def handle_top_level(my_pubkey):
    wait_for_new_tick = False
    current_block_hash = last_block()["h"]
    peer_whos_turn_it_is = ""

    while True:
        make_txn_with_probability(0)  # Make txn at level 0

        if wait_for_new_tick:
            time.sleep(0.5)
            check_block_hash = last_block()["h"]

            # Tick was put so continue
            if current_block_hash != check_block_hash:

                # Only toppest peer publishes info, rest wait
                if my_pubkey == peer_whos_turn_it_is:
                    block_info()
                else:
                    time.sleep(0.5)

                wait_for_new_tick = False
                current_block_hash = check_block_hash

        else:
            top_peers = peers_at_level[0]
            similarity_dict = get_sim_dict(top_peers, current_block_hash)

            my_score = similarity_dict[my_pubkey]

            sorted_peers = [(k, similarity_dict[k]) for k in
                            sorted(similarity_dict, key=similarity_dict.get,
                                   reverse=True)]

            # values = [item for item in similarity_dict.values()]
            # indices = sorted(range(len(values)), key=values.__getitem__)

            # Get peers ranked in descending order of score
            peer_whos_turn_it_is, _ = sorted_peers[0]

            # TODO: Simulate failure rate in putting within 5 sec window
            if my_pubkey == peer_whos_turn_it_is:
                wait_for_full_inbox(my_pubkey)

                content = messages(my_pubkey)

                new_hash = mine(content)

                block = construct_block(new_hash, content, utcnow())

                print_status(my_pubkey, my_score, logger.critical)

                chain.put(block)
            else:
                print_status(my_pubkey, my_score, logger.info)

            clear_inbox(my_pubkey)

            wait_for_new_tick = True


def handle_other_levels(my_pubkey, my_level):
    # For all other levels that are not level 0
    while True:
        make_txn_with_probability(my_level)

        peers_above_me = peers_at_level[my_level - 1]

        if my_level + 2 > len(peers_at_level):  # Here we are at the bottom
            peers_below_me = False
        else:
            # Here list exists but could be empty [] or have items
            peers_below_me = peers_at_level[my_level + 1]

        if peers_below_me:  # Leaf node if this is either [] or False
            wait_for_full_inbox(my_pubkey)

        content = messages(my_pubkey)

        new_hash = mine(content)

        # If you're a leaf node, this becomes a transaction (content is [])
        block = construct_block(new_hash, content, utcnow())

        inbox[random.choice(peers_above_me)].put(block)

        clear_inbox(my_pubkey)

        time.sleep(artificial_network_latency)  # Simulate network latency


# TODO: This adds a lot of variance to nr_added_txn! Only allow max 1 txn per V?
def make_txn_with_probability(my_level):
    if random.random() < txn_probability:
        new_hash = mine()
        txn = construct_block(new_hash, [], utcnow())

        # Assuming if we want to make a txn we send it to a peer / ourselves?
        my_level_peers = peers_at_level[my_level]
        inbox[random.choice(my_level_peers)].put(txn)


def verifier(i):
    my_pubkey, my_level = peer_ranked_list[i]

    if my_level == 0:
        handle_top_level(my_pubkey)
    else:
        handle_other_levels(my_pubkey, my_level)


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
    genesis_block = construct_block(genesis_hash, [], utcnow())
    chain.put(genesis_block)

    # Create simulated hierarchical list of peers, as gotten from tempus network
    peer_dict = {}
    for peer in range(nr_threads):
        pubkey = get_kp()[0]

        random_score = randint(0, nr_threads)

        peer_dict[pubkey] = random_score

    peerdict_sorted = sorted(peer_dict, key=peer_dict.get, reverse=True)

    # Calculate total amount of layers necessary based on desired nr of threads
    # Done by calculating a geometric series and using the formula for its sum
    highest_level_simulation_factor = 0
    total_sum = 0
    while total_sum < nr_threads:
        numerator = 1 - pow(branch_factor, highest_level_simulation_factor+1)
        denominator = 1 - branch_factor
        total_sum = top_level_peers * numerator / denominator  # Geometric serie
        highest_level_simulation_factor += 1

    logger.info("Highest level simulation factor: "
                + str(highest_level_simulation_factor))

    # Generate level progression with a geometric series using constants
    # Geometric series = [tlp, tlp*bf, tlp*bf^2, ..... , tlp*bf^hlsf]
    level_progression = [top_level_peers * branch_factor**i for i in
                         range(highest_level_simulation_factor)]

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

    # Initializing personal messaging queues ("inboxes") for each thread
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
