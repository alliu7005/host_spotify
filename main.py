from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth import default
import os
import json
from google.cloud import secretmanager
import uvicorn
import requests
from urllib.parse import unquote_plus
from spotipy.oauth2 import SpotifyOAuth

credentials, PROJECT_ID = default()
CLIENT_CONFIG_SECRET_ID = os.environ.get("GOOGLE_CLIENT_CONFIG_SECRET_ID")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://spotify-oauth-365383383851.us-central1.run.app/oauth2callback")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.middleware("http")
async def trust_x_forwarded_proto(request: Request, call_next):
    # If the load-balancer/proxy sent HTTPS, override the scheme
    proto = request.headers.get("x-forwarded-proto")
    if proto:
        request.scope["scheme"] = proto
    return await call_next(request)


def get_client_config_from_secret_manager():
    """Fetch the OAuth2 client configuration from Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    
    # Retrieve the latest version of the secret.
    secret_name = f"projects/{PROJECT_ID}/secrets/{CLIENT_CONFIG_SECRET_ID}/versions/latest"
    response = client.access_secret_version(request={"name":secret_name})
    secret_string = response.payload.data.decode("utf-8")
    
    try:
        return json.loads(secret_string)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error parsing secret JSON: {e}")
    
@app.get("/login")
def login(request: Request):
    client_config = get_client_config_from_secret_manager()
    agent_id    = request.query_params.get("agent_id")
    route = request.query_params.get("route")
    config = json.loads(unquote_plus(request.query_params.get("config")))
    scopes_param = request.query_params.get("scopes")
    if not agent_id or not scopes_param:
        raise HTTPException(400, "Missing agent_id or scopes")
    
    scopes = scopes_param.split(",")

    
    sp_oauth = SpotifyOAuth(
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        redirect_uri=REDIRECT_URI,
        scope=scopes
    )

    auth_url = sp_oauth.get_authorize_url()
    print("AUTH:", auth_url)

    state = json.dumps({
        "agent_id": agent_id,
        "scopes": scopes,
        "route": route,
        "config": config
    })
    
    # Set a secure, HTTP-only cookie with the state.
    redirect_response = RedirectResponse(url=auth_url)
    redirect_response.set_cookie(key="oauth_state", value=state, httponly=True)
    return redirect_response

@app.get("/oauth2callback")
def oauth2callback(request: Request):
    """
    Handle the callback from Google, exchange the authorization code for tokens,
    and store the credentials. In a production setting, these credentials should
    be stored securely and associated with the user's account.
    """
    state = request.cookies.get("oauth_state")

    payload = json.loads(state)
    agent_id = payload.get("agent_id")
    route = payload.get("route")
    scopes = payload.get("scopes")
    config = payload.get("config")

    code = request.query_params.get("code")
    client_config = get_client_config_from_secret_manager()
    sp_oauth = SpotifyOAuth(
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        redirect_uri=REDIRECT_URI,
        scope=scopes
    )
    token_info = sp_oauth.get_access_token(code, as_dict=False)
    print("TOKEN:", token_info)
     
    if not state:
        raise HTTPException(status_code=400, detail="Missing state; please try /login again.")

    # Store credentials in our in-memory session store for demonstration.
    resp = requests.post(f"https://{agent_id}.us-central1.run.app/store_credentials",json={
        "token": token_info
    }, headers={"Content-Type": "application/json"})

    resp.raise_for_status()
    
    # In a production app, link these credentials to the user account in your database.
    resp = requests.post(f"https://{agent_id}.us-central1.run.app/{route}", json=config, headers={"Content-Type": "application/json"})

    if not resp.ok:
        raise HTTPException(
            status_code=502,
            detail=f"Agent Failed {resp.status_code} {resp.text}"
        )

    return JSONResponse(
        status_code=resp.status_code,
        content=resp.json()
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips=True)
