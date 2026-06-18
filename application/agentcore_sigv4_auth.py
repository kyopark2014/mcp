import httpx
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


class AgentCoreSigV4Auth(httpx.Auth):
    def __init__(self, region: str, service: str = "bedrock-agentcore"):
        self.region = region
        self.service = service

    def auth_flow(self, request: httpx.Request):
        credentials = boto3.Session().get_credentials().get_frozen_credentials()
        headers = dict(request.headers)
        body = request.content

        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=body,
            headers=headers,
        )
        SigV4Auth(credentials, self.service, self.region).add_auth(aws_request)
        prepared = aws_request.prepare()

        for key, value in prepared.headers.items():
            request.headers[key] = value

        yield request
