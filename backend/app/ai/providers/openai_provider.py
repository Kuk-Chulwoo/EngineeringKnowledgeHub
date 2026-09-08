"""OpenAI Responses adapter. No SDK global state, tools, files, or automatic retries."""

import hashlib
import json

import httpx

from ...engineering.schema import canonical, digest
from .base import ProviderFailure, ProviderResult


class OpenAIProvider:
    def __init__(self, api_key: str, transport=None):
        self._api_key = api_key
        self._transport = transport

    def generate(self, model, prompt, content, schema, max_output_tokens):
        request = {
            "model": model,
            "store": False,
            "max_output_tokens": max_output_tokens,
            "input": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": canonical(content)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "engineering_extraction_0_1",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        raw = None

        def failure(code):
            error = ProviderFailure(code)
            error.request_sha256 = digest(request)
            error.response_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
            return error

        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(90, connect=10),
                    transport=self._transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "POST",
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": "Bearer " + self._api_key},
                    json=request,
                ) as response,
            ):
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raw = None  # A prefix is not a hash of the complete response.
                        raise failure("PROVIDER_RESPONSE_TOO_LARGE")
            result = json.loads(raw)
            if result.get("status") != "completed":
                raise failure("PROVIDER_INCOMPLETE")
            messages = [
                c
                for item in result.get("output", [])
                if item.get("type") == "message"
                for c in item.get("content", [])
            ]
            if len(messages) != 1 or messages[0].get("type") != "output_text":
                raise failure("PROVIDER_REFUSAL_OR_MALFORMED")
            payload = json.loads(messages[0]["text"])
            if not isinstance(payload, dict):
                raise failure("PROVIDER_MALFORMED")
            return ProviderResult(
                payload, digest(request), hashlib.sha256(raw).hexdigest(), result.get("model")
            )
        except httpx.TimeoutException as error:
            raw = None
            raise failure("PROVIDER_TIMEOUT") from error
        except httpx.HTTPError as error:
            raw = None
            raise failure("PROVIDER_HTTP_FAILURE") from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise failure("PROVIDER_MALFORMED") from error
