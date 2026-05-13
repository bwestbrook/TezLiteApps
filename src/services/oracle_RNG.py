import time
import os
import requests
import random
from pytezos import pytezos
from pytezos.crypto.key import Key

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
print('hi')
# Put your contract address here (Ghostnet first!)
CONTRACT_ADDRESS = "KT1VvcCnTPCUc7YaxyMT6opDrSPi2AUHnfvx"

# Oracle private key in environment variable
ORACLE_PRIVATE_KEY = os.getenv("ORACLE_KEY")

# RPC Node
RPC_URL = "https://rpc.tzkt.io/ghostnet"

# Better Call Dev API (for reading contract storage)
NETWORK = "ghostnet"
BCD_STORAGE_URL = f"https://api.better-call.dev/v1/contract/{NETWORK}/{CONTRACT_ADDRESS}/storage"

# Poll interval
POLL_SECONDS = 2
# --------------------------------------------------


# --------------------------------------------------
# 1. Load Oracle Client
# --------------------------------------------------
def load_oracle():
    if ORACLE_PRIVATE_KEY is None:
        raise Exception("ERROR: ORACLE_KEY environment variable not set.")


    seedPhrase = [
            'viable', 
            'spy', 
            'camp', 
            'win',
            'honey', 
            'impact', 
            'assist', 
            'town', 
            'parrot', 
            'abandon', 
            'similar', 
            'you', 
            'print', 
            'avocado', 
            'arrive', 
            'camp', 
            'maze', 
            'pet', 
            'secret', 
            'park',
            'thing', 
            'leg',
            'milk',
            'flush'
            ]
        
    key = Key.from_mnemonic(seedPhrase)

    client = pytezos.using(
        key=key,
        shell=RPC_URL
    )

    print("Oracle loaded. Address:", client.key.public_key_hash())
    return client


# --------------------------------------------------
# 2. Fetch storage from Better Call Dev
# --------------------------------------------------
def fetch_storage():
    try:
        res = requests.get(BCD_STORAGE_URL, timeout=10)
        res.raise_for_status()
        print(res)
    
        return res.json()[0]
    
    except Exception as e:
        print("Error fetching BCD storage:", e)
        return None


# --------------------------------------------------
# 3. Extract unfulfilled requests
# --------------------------------------------------
def get_unfulfilled_requests(storage):
    """
    storage: the dict returned by contract.storage() (Micheline-like).

    Returns a sorted list of unfulfilled request_ids (ints).
    """
    print(storage)
    # Top-level must have 'children'
    children = storage.get("children", [])
    if not children:
        print("ERROR: storage has no 'children'")
        return []

    # Find the 'requests' node among the children
    requests_node = None
    for child in children:
        if child.get("name") == "requests":
            requests_node = child
            break

    if requests_node is None:
        print("ERROR: could not find 'requests' node in storage")
        return []

    # 'requests_node["children"]' is a list of map entries
    games = requests_node.get("children", [])
    unfulfilled = []
    for game_info in games:
        for game_param in game_info['children']:
            if game_param['name'] == 'fulfilled':
                if not game_param['value']:
                    unfulfilled.append(game_info)

    return unfulfilled

# --------------------------------------------------
# 4. Generate random number (placeholder)
# --------------------------------------------------

def generate_random_numbers(n_randoms, max_random, exclusions):
    # TEMPORARY: Replace with your deterministic RNG logic
    rns = []
    while len(rns) < n_randoms:
        rn = random.randint(0, max_random)
        if rn not in exclusions:
            rns.append(rn)
            rns = list(sorted(set(rns)))
    rns_string = ''
    for rn in rns:
        rns_string += '{0},'.format(rn)

    print(rns, rns_string)
    return rns_string.strip()[:-1]

def generate_random_number():
    # TEMPORARY: Replace with your deterministic RNG logic
    return '{0}'.format(random.randint(0, 10**12))

# --------------------------------------------------
# 5. Fulfill request on-chain using PyTezos
# --------------------------------------------------
def fulfill_request(oracle_client, request_id, random_values):
    contract = oracle_client.contract(CONTRACT_ADDRESS)
    print(f" → Sending fulfillment: request_id={request_id}, random_values={random_values}")
    try:
        op = (
            contract.fulfillRequest(
                request_id=request_id,
                random_values=random_values,
                exc_1=-1,
                exc_2=-1
            )
            .with_amount(0)
            .as_transaction()
            .autofill()
            .sign()
            .inject()
        )
        print(" ✓ Fulfilled request", request_id)
        print("   Operation hash:", op["hash"])
    except Exception as e:
        print(" ✗ Error fulfilling request:", e)


# --------------------------------------------------
# 6. Full Oracle Loop
# --------------------------------------------------
def oracle_loop():
    oracle = load_oracle()

    print("\n🎲 Oracle is now running...\n")

    while True:
        print("--- Checking contract storage ---")

        storage = fetch_storage()
        if storage is None:
            time.sleep(POLL_SECONDS)
            continue

        unfulfilled = get_unfulfilled_requests(storage)

        if not unfulfilled:
            print("No pending requests.")
        else:
            print("Pending requests:", unfulfilled)

            for to_fill in unfulfilled:
                request_id = to_fill['name']
                n_randoms = int([x['value'] for x in to_fill['children'] if x['name'] == 'n_randoms'][0])
                max_random = int([x['value'] for x in to_fill['children'] if x['name'] == 'max_random'][0])
                exc_1 = int([x['value'] for x in to_fill['children'] if x['name'] == 'exc_1'][0])
                exc_2 = int([x['value'] for x in to_fill['children'] if x['name'] == 'exc_2'][0])
                exclusions = [exc_1, exc_2]
                #import ipdb;ipdb.set_trace()
                #print(request_id, n_randoms, max_random)
                rns = generate_random_numbers(n_randoms, max_random, exclusions)
                # 2. Fulfill on-chain
                fulfill_request(oracle, request_id, rns)

        time.sleep(POLL_SECONDS)


# --------------------------------------------------
# RUN ORACLE
# ------------------------------------------------
if __name__ == "__main__":
    fetch_storage()
    #
    oracle_loop()