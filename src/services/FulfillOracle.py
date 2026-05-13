import requests

# -------------------------------------------
# Replace this with your real contract address
# Example: KT1XXXXXXXXXXXXXXXXXXXXXXXXXXXX
contract_address = "KT1LSXDVwD1tGRzNQP9EVjdsAYYQRuNzCTVn"
# -------------------------------------------

# Choose the network: "mainnet", "ghostnet", "jakartanet", etc.
network = "ghostnet"   # Change to mainnet when ready

# Better Call Dev API endpoint for contract storage
url = f"https://api.better-call.dev/v1/contract/{network}/{contract_address}/storage"

def get_contract_storage():
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()   # raises exception for HTTP errors
        storage = response.json()
        print("=== Contract Storage Retrieved Successfully ===")
        print(storage)
        return storage
    except Exception as e:
        print("Error fetching storage:", e)

# Run the test fetch
if __name__ == "__main__":
    get_contract_storage()