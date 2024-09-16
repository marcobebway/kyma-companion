import json
import time
from http import HTTPStatus
from logging import Logger

import requests
from common.config import Config
from common.metrics import Metrics
from pydantic import BaseModel


class ConversationPayload(BaseModel):
    query: str = ""
    resource_kind: str
    resource_api_version: str
    resource_name: str
    namespace: str


class CompanionClient:
    config: Config

    def __init__(self, config: Config):
        self.config = config

    def __get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.companion_token}",
            "X-Cluster-Certificate-Authority-Data": self.config.test_cluster_ca_data,
            "X-Cluster-Url": self.config.test_cluster_url,
            "X-K8s-Authorization": self.config.test_cluster_auth_token,
            "Content-Type": "application/json",
        }

    def fetch_initial_questions(
        self, payload: ConversationPayload, logger: Logger
    ) -> str:
        logger.debug(
            f"querying Companion: {self.config.companion_api_url} for initial questions..."
        )

        req_session = requests.Session()
        start_time = time.time()
        response = req_session.post(
            f"{self.config.companion_api_url}/api/conversations",
            json.dumps(payload.model_dump()),
            headers=self.__get_headers(),
        )
        if response.status_code != HTTPStatus.OK:
            raise ValueError(
                f"failed to get response (status: {response.status_code}). "
                f"Response: {response.text}"
            )

        # record the response time.
        Metrics.get_instance().record_init_conversation_response_time(
            time.time() - start_time
        )

        return response

    def get_companion_response(
        self, conversation_id: str, payload: ConversationPayload, logger: Logger
    ) -> str:
        headers = self.__get_headers()
        headers["session-id"] = conversation_id

        uri = f"{self.config.companion_api_url}/api/conversations/{conversation_id}/messages"
        req_session = requests.Session()
        start_time = time.time()
        response = req_session.post(
            uri, json.dumps(payload.model_dump()), headers=headers, stream=True
        )
        if response.status_code != HTTPStatus.OK:
            raise ValueError(
                f"failed to get response from the utils API (status: {response.status_code}). "
                f"Response: {response.text}"
            )

        answer = self.__extract_final_response(response)

        # record the response time.
        Metrics.get_instance().record_conversation_response_time(
            time.time() - start_time
        )

        return answer

    def __extract_final_response(self, response) -> str:
        """read the stream response and extract the final response from it. Timeout is in seconds."""
        start_time = time.time()
        # extract the final response from the response.
        for chunk in response.iter_lines():
            # check for timeout.
            if time.time() - start_time > self.config.streaming_response_timeout:
                raise Exception("timeout while waiting for the final response")

            # sometimes it can return multiple chunks in the response.
            # so we need to extract the last chunk.
            lines = chunk.splitlines()
            obj = json.loads(lines[-1])

            # if the status is not OK, raise an exception.
            if "status" not in obj:
                raise Exception(f"status key not found in the response: {obj}")
            if obj["status"] != HTTPStatus.OK:
                raise Exception(f"companion response status: {obj}")

            # if the data key is not found, continue.
            if "data" not in obj:
                continue

            # if the data is a string, convert it to a json object.
            data = obj["data"]
            if isinstance(obj["data"], str):
                data = json.loads(obj["data"])

            # if the finalizer key is found, return the final answer.
            if "Finalizer" in data:
                messages = data["Finalizer"]["messages"]
                if len(messages) == 0:
                    raise Exception("no final answer found by the companion")
                return messages[-1]["content"]

            # if the Exit key is found, raise an exception.
            if "Exit" in obj["data"]:
                raise Exception("kyma companion went into error node")
