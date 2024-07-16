import asyncio
import base64
import json
import os
import tempfile
import time

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from routers import chat


def sanitizeResponse(response):
    if isinstance(response, dict):
        if response["kind"] == "SecretList":
            return sanitizeSecretList(response)
        return response
    elif isinstance(response, list):
        if response[0]["kind"] == "Secret":
            return sanitizeSecret(response)
        return response
    else:
        raise Exception("Unexpected object.")


def sanitizeSecretList(secretList):
    items = []
    for secret in secretList["items"]:
        items.append(sanitizeSecret(secret))

    secretList["items"] = items
    return secretList


def sanitizeSecret(secret):
    secret["data"] = {}
    return secret


def executeRESTCall(URI, apiServer, userToken, certificateAuthData):
    # decode the certificate authority data from base64
    ca_data = base64.b64decode(certificateAuthData)  # .decode('utf-8')

    # write the certificate authority data to a temporary file
    ca_file = tempfile.NamedTemporaryFile(delete=False)
    ca_file.write(ca_data)
    ca_file.close()

    # define headers for the API request
    headers = {
        "Authorization": userToken,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Make the API request
    response = requests.get(url=apiServer + URI, headers=headers, verify=ca_file.name)

    # Delete the temporary file
    os.unlink(ca_file.name)

    return sanitizeResponse(response.json())


app = FastAPI()
app.include_router(chat.router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def read_certificate_auth_data(request: Request) -> str:
    return request.headers.get("X-Cluster-Certificate-Authority-Data", "")


def read_user_token(request: Request) -> str:
    return request.headers.get("X-K8s-Authorization", "")


def get_api_server(request: Request) -> str:
    return request.headers.get("X-Cluster-Url", "")


async def pods_json_streamer(pods):
    t0 = time.time()
    for pod in pods:
        podInfo = {
            "namespace": pod["metadata"]["namespace"],
            "name": pod["metadata"]["name"],
        }
        print(f"{podInfo}", flush=True)
        yield json.dumps(podInfo) + "\n"
        await asyncio.sleep(0.5)
    print(f"Over (time {int((time.time()-t0)*1000)}ms)", flush=True)


@app.get("/")
async def root(request: Request) -> dict:  # noqa E302
    return {"message": "Hello World"}


@app.get("/api/v1/pods")
async def pods(request: Request) -> dict:  # noqa E302
    # get request headers
    certificateAuthData = read_certificate_auth_data(request)
    userToken = read_user_token(request)
    apiServer = get_api_server(request)

    # print request headers
    print(f"cluster_certificate_authority_data: {certificateAuthData}", flush=True)
    print(f"k8s_authorization: {userToken}", flush=True)
    print(f"cluster_url: {apiServer}", flush=True)

    # check if any of the above headers are missing
    if not certificateAuthData or not userToken or not apiServer:
        return {"error": "Missing required headers"}

    results = executeRESTCall("/api/v1/pods", apiServer, userToken, certificateAuthData)
    if "items" in results:
        return {"pods": results["items"]}
    return {}


@app.get("/api/v1/pods/stream")
async def pods_stream(request: Request) -> dict:  # noqa E302
    # get request headers
    certificateAuthData = read_certificate_auth_data(request)
    userToken = read_user_token(request)
    apiServer = get_api_server(request)

    # print request headers
    print(f"cluster_certificate_authority_data: {certificateAuthData}\n", flush=True)
    print(f"k8s_authorization: {userToken}\n", flush=True)
    print(f"cluster_url: {apiServer}\n", flush=True)

    # check if any of the above headers are missing
    if not certificateAuthData or not userToken or not apiServer:
        return {"error": "Missing required headers"}

    results = executeRESTCall("/api/v1/pods", apiServer, userToken, certificateAuthData)
    if "items" in results:
        return StreamingResponse(
            pods_json_streamer(results["items"]), media_type="text/event-stream"
        )
    return {}
