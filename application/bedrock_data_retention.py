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
FABLE_RETENTION_ENSURED = False
BEDROCK_DATA_RETENTION_URL = "https://bedrock.{region}.amazonaws.com/data-retention"
MANTLE_DATA_RETENTION_URL = "https://bedrock-mantle.{region}.api.aws/v1/data_retention"
OPT_IN_MODE = "provider_data_share"
DEFAULT_REGION = "us-east-1"
FABLE_BEDROCK_REGIONS = ("us-west-2", "us-east-1", "us-east-2")
CONFIG_KEY = "fable_data_retention_opt_in"


def _get_account_id() -> str:
    import utils

    account_id = utils.config.get("accountId")
    if account_id:
        return str(account_id)

    sts = boto3.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    utils.config["accountId"] = account_id
    return str(account_id)


def _is_fable_opt_in_recorded(account_id: str) -> bool:
    import utils

    recorded = utils.config.get(CONFIG_KEY)
    if isinstance(recorded, dict):
        return (
            recorded.get("completed") is True
            and str(recorded.get("account_id", "")) == account_id
        )
    return recorded is True


def _record_fable_opt_in(account_id: str) -> None:
    import utils

    utils.config[CONFIG_KEY] = {
        "completed": True,
        "account_id": account_id,
    }
    try:
        with open(utils.config_path, "w", encoding="utf-8") as config_file:
            json.dump(utils.config, config_file, indent=2, ensure_ascii=False)
        logger.info(
            "Recorded Fable data retention opt-in in config.json for account %s",
            account_id,
        )
    except Exception as error:
        logger.warning("Failed to record Fable opt-in in config.json: %s", error)


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
        return True, ""

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
    global FABLE_RETENTION_ENSURED

    if "fable" not in model_id.lower():
        return True

    if FABLE_RETENTION_ENSURED:
        return True

    account_id = _get_account_id()
    if _is_fable_opt_in_recorded(account_id):
        FABLE_RETENTION_ENSURED = True
        OPTED_IN_REGIONS.update(FABLE_BEDROCK_REGIONS)
        if bedrock_region:
            OPTED_IN_REGIONS.add(bedrock_region)
        return True

    regions = []
    for region in (bedrock_region, *FABLE_BEDROCK_REGIONS):
        if region not in regions:
            regions.append(region)

    all_success = True
    for region in regions:
        success, message = opt_in_provider_data_share(region=region)
        if success:
            if message:
                logger.info("Bedrock data retention opt-in: %s", message)
        else:
            logger.warning("Bedrock data retention opt-in failed: %s", message)
            all_success = False

    if all_success:
        FABLE_RETENTION_ENSURED = True
        _record_fable_opt_in(account_id)

    return all_success
