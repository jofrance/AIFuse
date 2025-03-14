import time
import threading
from msal import PublicClientApplication
import config

scopes=config.scopes

def get_access_token():
    """Acquire an access token using MSAL."""
    if config.msal_app is None:
        config.msal_app = PublicClientApplication(
            client_id = config.client_id,
            authority = config.authority,
            #enable_broker_on_windows=True
        )
    accounts = config.msal_app.get_accounts()
    result = None
    if accounts:
        result = config.msal_app.acquire_token_silent(scopes, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]
    result = config.msal_app.acquire_token_interactive(scopes)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception('Failed to get access token')

def refresh_token(stop_event):
    """Background thread to refresh token every hour."""
    while not stop_event.is_set():
        try:
            new_token = get_access_token()
            with config.token_lock:
                config.access_token = new_token
            print("Access token refreshed.")
        except Exception as e:
            print(f"Error refreshing access token: {e}")
        stop_event.wait(3600)

