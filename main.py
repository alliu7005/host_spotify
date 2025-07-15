from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth import default
import os
import json
from google.cloud import secretmanager
import uvicorn
import requests
from urllib.parse import unquote_plus, quote_plus
from spotipy.oauth2 import SpotifyOAuth

credentials, PROJECT_ID = default()
CLIENT_CONFIG_SECRET_ID = os.environ.get("GOOGLE_CLIENT_CONFIG_SECRET_ID")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://spotify-oauth-206239759924.us-central1.run.app/oauth2callback")

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
    scopes_param = request.query_params.get("scopes")
    return_url = request.query_params.get("return_url")
    
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
        "scopes": scopes,
        "return_url": return_url
    })
    
    # Set a secure, HTTP-only cookie with the state.
    redirect_response = RedirectResponse(url=auth_url)
    redirect_response.set_cookie(key="oauth_state", value=quote_plus(state), httponly=True, secure=False, samesite="lax", path="/")
    return redirect_response

@app.get("/oauth2callback")
def oauth2callback(request: Request):
    """
    Handle the callback from Google, exchange the authorization code for tokens,
    and store the credentials. In a production setting, these credentials should
    be stored securely and associated with the user's account.
    """
    state = unquote_plus(request.cookies.get("oauth_state"))
    payload = json.loads(state)
    
    scopes = payload.get("scopes")
    return_url = payload.get("return_url")

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
    #resp = requests.post(f"https://us-central1-aiplatform.googleapis.com/v1/projects/365383383851/locations/us-central1/endpoints/{agent_id}:store_credentials",json={
    #    "token": token_info
    #}, headers={"Content-Type": "application/json"})

    #resp.raise_for_status()
    
    # In a production app, link these credentials to the user account in your database.
    #resp = requests.post(f"https://{agent_id}.us-central1.run.app/{route}", json=config, headers={"Content-Type": "application/json"})
    return RedirectResponse(
        url=f"{return_url}?token={token_info}"
        , status_code=303
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips=True)
