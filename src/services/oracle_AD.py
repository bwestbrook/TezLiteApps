import time
import os
import requests
import random
from pprint import pprint
from pytezos import pytezos
from pytezos.crypto.key import Key

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
#print('hi')
# Put your contract address here (Ghostnet first!)
CONTRACT_ADDRESS = "KT1LQTALXvukm56XA1p1BcRrGi36tMyWnXp5"
ORACLE_CONTRACT_ADDRESS = "KT1VvcCnTPCUc7YaxyMT6opDrSPi2AUHnfvx"

# Oracle private key in environment variable
ORACLE_PRIVATE_KEY = os.getenv("ORACLE_KEY")

# RPC Node
RPC_URL = "https://rpc.tzkt.io/ghostnet"

# Better Call Dev API (for reading contract storage)
NETWORK = "ghostnet"
BCD_AD_STORAGE_URL = f"https://api.better-call.dev/v1/contract/{NETWORK}/{CONTRACT_ADDRESS}/storage"
BCD_ORA_STORAGE_URL = f"https://api.better-call.dev/v1/contract/{NETWORK}/{ORACLE_CONTRACT_ADDRESS}/storage"

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
def fetch_storage_ad():
    try:
        res = requests.get(BCD_AD_STORAGE_URL, timeout=10)
        res.raise_for_status()
        return res.json()[0]
    except Exception as e:
        print("Error fetching BCD storage:", e)
        return None
    
def fetch_storage_ora():
    try:
        res = requests.get(BCD_ORA_STORAGE_URL, timeout=10)
        res.raise_for_status()
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
    #print(storage)
    # Top-level must have 'children'
    children = storage.get("children", [])
    if not children:
        print("ERROR: storage has no 'children'")
        return []

    # Find the 'requests' node among the children
    requests_node = None
    for child in children:
        #print(child)
        if child.get("name") == "games":
            requests_node = child
            break

    if requests_node is None:
        print("ERROR: could not find 'requests' node in storage")
        return []

    # 'requests_node["children"]' is a list of map entries
    entries = requests_node.get("children", [])
   
    unfulfilled = {}

    for entry in entries:
        # entry["name"] is the key in the map (request_id as string)
        req_id_str = entry.get("name")
        game_params = entry.get("children")
        player = [x['value'] for x in game_params if x['name'] == 'player'][0]
        game_status = [x['value'] for x in game_params if x['name'] == 'status'][0]
        bet = [x['value'] for x in game_params if x['name'] == 'bet'][0]
        unfulfilled[req_id_str] = {'player': player, 'game_status': game_status, 'bet': bet}
    
    return unfulfilled


# --------------------------------------------------
# 5. Fulfill request on-chain using PyTezos
# --------------------------------------------------

def get_first_cards_from_oracle(game_id):
    
    ora_storage = fetch_storage_ora()
    children = ora_storage.get("children", [])
    requests = [x for x in children if x['name'] == 'requests']
    has_cards = False
    first_card = -1
    second_card = -1
    for request in requests:
        all_game_ids = [x['name'] for x in request['children']]
        #import ipdb;ipdb.set_trace()
        if game_id in all_game_ids:
            game_idx = all_game_ids.index(game_id)
            request['children'][game_idx]
            fulfilled = [x['value'] for x in request['children'][game_idx]['children'] if x['name'] == 'fulfilled'][0]
            #import ipdb;ipdb.set_trace()
            if fulfilled:
                random_numbers = [x['value'] for x in request['children'][game_idx]['children'] if x['name'] == 'random_values'][0]
                first_card = int(random_numbers.split(',')[0].strip())
                second_card = int(random_numbers.split(',')[1].strip())
                has_cards = True
        
    return has_cards, [first_card, second_card]

def get_second_card_from_oracle(game_id):
    
    ora_storage = fetch_storage_ora()
    children = ora_storage.get("children", [])
    requests = [x for x in children if x['name'] == 'requests']
    has_card = False
    last_card = -1
    for request in requests:
        all_game_ids = [x['name'] for x in request['children']]
        if game_id in all_game_ids:
            game_idx = all_game_ids.index(game_id)
            request['children'][game_idx]
            fulfilled = [x['value'] for x in request['children'][game_idx]['children'] if x['name'] == 'fulfilled'][0]
            #import ipdb;ipdb.set_trace()
            if fulfilled:
                random_number = [x['value'] for x in request['children'][game_idx]['children'] if x['name'] == 'random_values'][0]
                last_card = int(random_number)
                has_card = True
    return has_card, last_card
            

def send_second_card_from_oracle(oracle_client, game_id, last_card, player):          
    ad_contract = oracle_client.contract(CONTRACT_ADDRESS)
    game_id = game_id.replace('R2', 'R1')
    #import ipdb;ipdb.set_trace()
    try:
        op = (
                ad_contract.lastCard(
                    card3=last_card,             
                    game_id=game_id,
                    player=player
                )
            .with_amount(0)
            .as_transaction()
            .autofill()
            .sign()
            .inject()
        )
        print(" ✓ Fulfilled request", game_id)
        print("   Operation hash:", op["hash"])
    except Exception as e:
        print(" ✗ Error fulfilling request:", e)


def send_first_cards_from_oracle(oracle_client, game_id, first_cards):   
    ad_contract = oracle_client.contract(CONTRACT_ADDRESS)            
    try:
        op = (
                ad_contract.firstCards(
                    card1=first_cards[0],
                    card2=first_cards[1],              
                    game_id=game_id
                )
            .with_amount(0)
            .as_transaction()
            .autofill()
            .sign()
            .inject()
        )
        print(" ✓ Fulfilled request", game_id)
        print("   Operation hash:", op["hash"])
    except Exception as e:
        print(" ✗ Error fulfilling request:", e)

def request_first_cards_random_numbers(oracle_client, full_game_id):
    oracle_contract = oracle_client.contract(ORACLE_CONTRACT_ADDRESS)
    try:
        op = (
            oracle_contract.makeRequest(
                tag=full_game_id,
                max_random=51,
                n_randoms=2,
                exc_1=-1,
                exc_2=-1
            )
            .with_amount(0)
            .as_transaction()
            .autofill()
            .sign()
            .inject()
        )
        print(" ✓ Fulfilled request", full_game_id)
        print("   Operation hash:", op["hash"])
    except Exception as e:
        print(" ✗ Error fulfilling request:", e)

def request_second_card_random_number(oracle_client, full_game_id):
    oracle_contract = oracle_client.contract(ORACLE_CONTRACT_ADDRESS)
    try:
        op = (
            oracle_contract.makeRequest(
                tag=full_game_id,
                max_random=52,
                n_randoms=1,
                exc_1=-1,
                exc_2=-1
            )
            .with_amount(0)
            .as_transaction()
            .autofill()
            .sign()
            .inject()
        )
        print(" ✓ Fulfilled request", full_game_id)
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
        ad_storage = fetch_storage_ad()
        if ad_storage is None:
            time.sleep(POLL_SECONDS)
            continue
        unfulfilled = get_unfulfilled_requests(ad_storage)
        if not unfulfilled:
            print("No pending requests.")
        else:
            print("Pending requests:", unfulfilled)
            first_cards = [-1, -1]
            for game_id, game_params in unfulfilled.items():
                player = game_params['player']
                game_status = game_params['game_status']
                if game_status == '0':
                    has_cards = False
                    try:
                        has_cards, first_cards = get_first_cards_from_oracle(game_id)
                    except Exception as e:
                        print()
                        print(" ✗ Error getting first cards from oracle request:", e)
                    if has_cards:
                        try:
                            send_first_cards_from_oracle(oracle, game_id, first_cards)
                        except Exception as e:
                            print()
                            print(" ✗ Error sending first cards from oracle request:", e)
                    if not has_cards:
                        try:
                            print()
                            print('Request random numbers for first cards from oracle {0}'.format(game_id))
                            rng_request_id = '{0}-{1}'.format(game_id, player)
                            request_first_cards_random_numbers(oracle, game_id)
                        except Exception as e:
                            print()
                            print('Requsting first cards')
                            print(" ✗ Error fulfilling request:", e)
                elif game_status == '2':
                    has_cards = False
                    try:
                        print()
                        print()
                        
                        game_id = game_id.replace('R1', 'R2')
                        print('Getting second card', game_id)
                        has_cards, last_card = get_second_card_from_oracle(game_id)
                    except Exception as e:
                        print('')
                        print('Error getting second card')
                        print(" ✗ Error fulfilling request:", e)
                    if has_cards:
                        try:
                            send_second_card_from_oracle(oracle, game_id, last_card, player)
                        except Exception as e:
                            print()
                            print(" ✗ Error sending first cards from oracle request:", e)
                    if not has_cards:
                        try:
                            print('request random number for second card from oracle')
                            game_id = game_id.replace('R1', 'R2')
                            request_second_card_random_number(oracle, game_id)
                        except Exception as e:
                            print(" ✗ Error fulfilling request:", e)
        time.sleep(POLL_SECONDS)




# --------------------------------------------------
# RUN ORACLE
# ------------------------------------------------
if __name__ == "__main__":
    fetch_storage_ad()
    fetch_storage_ora()
    #
    oracle_loop()