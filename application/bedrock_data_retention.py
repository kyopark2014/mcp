import json
import logging
import os
import urllib.error
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

logger = logging.getLogger(__name__)

OPTED_IN_REGIONS: set[str] = set()
BEDROCK_DATA_RETENTION_URL = "https://bedrock.{region}.amazonaws.com/data-retention"
MANTLE_DATA_RETENTION_URL = "https://bedrock-mantle.{region}.api.aws/v1/data_retention"
OPT_IN_MODE = "provider_data_share"
DEFAULT_REGION = "us-east-1"
FABLE_BEDROCK_REGIONS = ("us-west-2", "us-east-1", "us-east-2")


def _get_bearer_token(region: str) -> str:
    token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if token:
        return token

    from aws_bedrock_token_generator import provide_token

    return provide_token(region=region)


def get_bedrock_bearer_token(region: str) -> str:
    return _get_bearer_token(region)


def _request_bedrock_control_plane(
    method: str, region: str, body: dict | None = None
) -> tuple[int, str]:
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    url = BEDROCK_DATA_RETENTION_URL.format(region=region)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    request = AWSRequest(method=method, url=url, data=payload, headers=headers)
    SigV4Auth(credentials, "bedrock", region).add_auth(request)
    prepared = request.prepare()
    http_request = urllib.request.Request(
        prepared.url,
        data=payload,
        method=method,
        headers=dict(prepared.headers),
    )
    with urllib.request.urlopen(http_request, timeout=30) as response:
        return response.status, response.read().decode()


def _request_mantle(method: str, region: str, body: dict | None = None) -> tuple[int, str]:
    token = _get_bearer_token(region)
    url = MANTLE_DATA_RETENTION_URL.format(region=region)
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read().decode()


def get_data_retention_mode(region: str = DEFAULT_REGION) -> tuple[bool, str]:
    try:
        status, body = _request_bedrock_control_plane("GET", region)
        return True, f"HTTP {status}: {body}"
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}: {error.read().decode()}"
    except Exception as error:
        return False, str(error)


def opt_in_provider_data_share(region: str = DEFAULT_REGION) -> tuple[bool, str]:
    if region in OPTED_IN_REGIONS:
        return True, f"already opted in for {region}"

    try:
        status, body = _request_bedrock_control_plane(
            "PUT", region, {"mode": OPT_IN_MODE}
        )
        OPTED_IN_REGIONS.add(region)
        return True, f"bedrock control plane ({region}) HTTP {status}: {body or OPT_IN_MODE}"
    except urllib.error.HTTPError as control_plane_error:
        control_plane_message = control_plane_error.read().decode()
    except Exception as control_plane_error:
        control_plane_message = str(control_plane_error)

    try:
        status, body = _request_mantle("PUT", region, {"mode": OPT_IN_MODE})
        OPTED_IN_REGIONS.add(region)
        return True, f"bedrock-mantle ({region}) HTTP {status}: {body or OPT_IN_MODE}"
    except urllib.error.HTTPError as mantle_error:
        mantle_message = mantle_error.read().decode()
        return False, (
            f"Failed to opt in for {region}. "
            f"bedrock control plane: {control_plane_message}; "
            f"bedrock-mantle: HTTP {mantle_error.code}: {mantle_message}"
        )
    except Exception as mantle_error:
        return False, (
            f"Failed to opt in for {region}. "
            f"bedrock control plane: {control_plane_message}; "
            f"bedrock-mantle: {mantle_error}"
        )


def ensure_fable_data_retention(
    model_id: str,
    bedrock_region: str = DEFAULT_REGION,
) -> bool:
    if "fable" not in model_id.lower():
        return True

    regions = []
    for region in (bedrock_region, *FABLE_BEDROCK_REGIONS):
        if region not in regions:
            regions.append(region)

    all_success = True
    for region in regions:
        success, message = opt_in_provider_data_share(region=region)
        if success:
            logger.info("Bedrock data retention opt-in: %s", message)
        else:
            logger.warning("Bedrock data retention opt-in failed: %s", message)
            all_success = False

    return all_success
