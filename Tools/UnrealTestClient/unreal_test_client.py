"""Minimal Unreal Test Client SDK."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional
from urllib import error, parse, request


class UnrealTestClientError(RuntimeError):
    """Base client error."""


class UnrealTestClientTimeoutError(UnrealTestClientError):
    """Raised when a polling operation times out."""


JsonObject = Dict[str, Any]
Predicate = Callable[[Mapping[str, Any]], bool]
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass
class _RequestConfig:
    timeout: float
    retry_attempts: int
    retry_backoff: float


@dataclass
class _WebSocketEndpoint:
    url: str
    host: str
    port: int
    resource: str
    secure: bool


@dataclass
class _WebSocketWaitOutcome:
    event: Optional[Mapping[str, Any]]
    cursor: int
    timed_out: bool


class _WebSocketTransportError(RuntimeError):
    def __init__(self, message: str, *, cursor: int) -> None:
        super().__init__(message)
        self.cursor = cursor


class _MinimalWebSocketClient:
    def __init__(self, endpoint: _WebSocketEndpoint, timeout: float) -> None:
        self._endpoint = endpoint
        self._timeout = max(0.1, timeout)
        self._socket: Optional[socket.socket] = None

    def __enter__(self) -> "_MinimalWebSocketClient":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def connect(self) -> None:
        raw_socket = socket.create_connection((self._endpoint.host, self._endpoint.port), timeout=self._timeout)
        if self._endpoint.secure:
            context = ssl.create_default_context()
            raw_socket = context.wrap_socket(raw_socket, server_hostname=self._endpoint.host)
        raw_socket.settimeout(self._timeout)
        self._socket = raw_socket

        client_key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {self._endpoint.resource} HTTP/1.1\r\n"
            f"Host: {self._endpoint.host}:{self._endpoint.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {client_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self._socket.sendall(handshake)

        response = self._recv_http_headers()
        self._validate_handshake(response, client_key)

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.close()
        finally:
            self._socket = None

    def recv_json(self, *, deadline: float) -> Optional[Mapping[str, Any]]:
        message = self.recv_text(deadline=deadline)
        if message is None:
            return None
        payload = json.loads(message)
        if not isinstance(payload, Mapping):
            raise ValueError("websocket payload must be a JSON object")
        return payload

    def recv_text(self, *, deadline: float) -> Optional[str]:
        while True:
            frame = self._recv_frame(deadline=deadline)
            if frame is None:
                return None
            opcode, payload = frame
            if opcode == 0x1:
                return payload.decode("utf-8")
            if opcode == 0x8:
                raise ConnectionError("websocket closed by server")
            if opcode == 0x9:
                self._send_control_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            raise ValueError(f"unsupported websocket opcode: {opcode}")

    def _recv_http_headers(self) -> str:
        chunks = bytearray()
        assert self._socket is not None
        while b"\r\n\r\n" not in chunks:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake connection closed")
            chunks.extend(chunk)
            if len(chunks) > 16384:
                raise ValueError("websocket handshake response too large")
        return chunks.decode("ascii", errors="replace")

    def _validate_handshake(self, response: str, client_key: str) -> None:
        lines = response.split("\r\n")
        if not lines or "101" not in lines[0]:
            raise ConnectionError(f"unexpected websocket handshake status: {lines[0] if lines else 'empty response'}")

        headers: Dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        accept_key = headers.get("sec-websocket-accept", "")
        expected_accept = base64.b64encode(hashlib.sha1(f"{client_key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        if accept_key != expected_accept:
            raise ConnectionError("invalid websocket accept key")

    def _recv_frame(self, *, deadline: float) -> Optional[tuple[int, bytes]]:
        header = self._recv_exact(2, deadline=deadline)
        if header is None:
            return None

        first_byte, second_byte = header[0], header[1]
        opcode = first_byte & 0x0F
        masked = (second_byte & 0x80) != 0
        payload_length = second_byte & 0x7F

        if payload_length == 126:
            extended = self._recv_exact(2, deadline=deadline)
            if extended is None:
                return None
            payload_length = int.from_bytes(extended, "big")
        elif payload_length == 127:
            extended = self._recv_exact(8, deadline=deadline)
            if extended is None:
                return None
            payload_length = int.from_bytes(extended, "big")

        mask_key = b""
        if masked:
            mask_key = self._recv_exact(4, deadline=deadline) or b""
            if len(mask_key) != 4:
                return None

        payload = self._recv_exact(payload_length, deadline=deadline)
        if payload is None:
            return None

        if masked:
            payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, length: int, *, deadline: float) -> Optional[bytes]:
        if length == 0:
            return b""

        assert self._socket is not None
        chunks = bytearray()
        while len(chunks) < length:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                return None
            self._socket.settimeout(min(self._timeout, max(0.05, remaining_time)))
            try:
                chunk = self._socket.recv(length - len(chunks))
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("websocket connection closed while receiving frame")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_control_frame(self, opcode: int, payload: bytes) -> None:
        if self._socket is None:
            return
        frame = bytearray()
        frame.append(0x80 | (opcode & 0x0F))
        payload_length = len(payload)
        if payload_length > 125:
            raise ValueError("control frames must be <= 125 bytes")
        frame.append(0x80 | payload_length)
        mask_key = os.urandom(4)
        frame.extend(mask_key)
        frame.extend(payload[index] ^ mask_key[index % 4] for index in range(payload_length))
        self._socket.sendall(frame)


class UnrealTestClient:
    """Simple HTTP client for the Unreal test remote API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        retry_attempts: int = 2,
        retry_backoff: float = 0.25,
        session_id: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._config = _RequestConfig(timeout=timeout, retry_attempts=max(0, retry_attempts), retry_backoff=max(0.0, retry_backoff))
        self._session_id = session_id
        self._connected = False
        self._capabilities_cache: Optional[JsonObject] = None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> JsonObject:
        health = self._request("GET", "/health")
        self._connected = True
        return health

    def disconnect(self) -> None:
        self._connected = False
        self._session_id = None
        self._capabilities_cache = None

    def get_capabilities(self) -> JsonObject:
        capabilities = self._request("GET", "/capabilities")
        self._capabilities_cache = capabilities
        return capabilities

    def start_session(
        self,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> JsonObject:
        payload: JsonObject = {}
        if session_id:
            payload["session_id"] = session_id
        if run_id:
            payload["run_id"] = run_id
        if options:
            payload.update(dict(options))

        response = self._request("POST", "/session/start", json_body=payload)
        session_value = response.get("session_id")
        if isinstance(session_value, str) and session_value:
            self._session_id = session_value
        elif session_id:
            self._session_id = session_id
        return response

    def stop_session(self, session_id: Optional[str] = None) -> JsonObject:
        resolved_session_id = self._resolve_session_id(session_id)
        response = self._request("POST", "/session/stop", json_body={"session_id": resolved_session_id})
        if self._session_id == resolved_session_id:
            self._session_id = None
        return response

    def send_command(
        self,
        command: str,
        *,
        args: Optional[Mapping[str, Any]] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> JsonObject:
        resolved_session_id = self._resolve_session_id(session_id)
        payload: JsonObject = {"session_id": resolved_session_id, "command": command}
        if trace_id:
            payload["trace_id"] = trace_id
        if args is not None:
            payload["args"] = dict(args)
        return self._request("POST", "/command/execute", json_body=payload, allow_http_error_json=True)

    def get_player_state(
        self,
        *,
        session_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        target_id: Optional[str] = None,
    ) -> JsonObject:
        return self._request(
            "GET",
            "/state/player",
            query=self._build_query(session_id=session_id, actor_id=actor_id, target_id=target_id),
        )

    def get_target_state(
        self,
        *,
        session_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        player_actor_id: Optional[str] = None,
    ) -> JsonObject:
        return self._request(
            "GET",
            "/state/target",
            query=self._build_query(session_id=session_id, actor_id=actor_id, player_actor_id=player_actor_id),
        )

    def get_spatial_state(
        self,
        *,
        session_id: Optional[str] = None,
        player_actor_id: Optional[str] = None,
        target_actor_id: Optional[str] = None,
        distance_cm: Optional[float] = None,
        yaw_delta_degrees: Optional[float] = None,
        recommended_left_stick_x: Optional[float] = None,
        recommended_left_stick_y: Optional[float] = None,
        navigation_path_length_cm: Optional[float] = None,
        line_of_sight: Optional[bool] = None,
        target_in_attack_range: Optional[bool] = None,
    ) -> JsonObject:
        query = self._build_query(
            session_id=session_id,
            player_actor_id=player_actor_id,
            target_actor_id=target_actor_id,
        )
        self._append_optional_number(query, "distance_cm", distance_cm)
        self._append_optional_number(query, "yaw_delta_degrees", yaw_delta_degrees)
        self._append_optional_number(query, "recommended_left_stick_x", recommended_left_stick_x)
        self._append_optional_number(query, "recommended_left_stick_y", recommended_left_stick_y)
        self._append_optional_number(query, "navigation_path_length_cm", navigation_path_length_cm)
        self._append_optional_bool(query, "line_of_sight", line_of_sight)
        self._append_optional_bool(query, "target_in_attack_range", target_in_attack_range)
        return self._request("GET", "/state/spatial", query=query)

    def get_screenshot(
        self,
        *,
        session_id: Optional[str] = None,
        query: Optional[Mapping[str, Any]] = None,
        height: int = 360,
        preserve_aspect_ratio: bool = True,
        jpeg_quality: int = 60,
    ) -> JsonObject:
        query_params = self._build_query(session_id=session_id)
        if query is not None:
            query_params.update(dict(query))

        query_params["height"] = str(int(height))
        query_params["preserve_aspect_ratio"] = "true" if preserve_aspect_ratio else "false"
        query_params["jpeg_quality"] = str(int(jpeg_quality))
        return self._request("GET", "/capture/screenshot", query=query_params, allow_http_error_json=True)

    def capture_viewport(
        self,
        *,
        session_id: Optional[str] = None,
        height: int = 360,
        preserve_aspect_ratio: bool = True,
        jpeg_quality: int = 60,
    ) -> JsonObject:
        query_params = self._build_query(session_id=session_id)
        query_params["height"] = str(int(height))
        query_params["preserve_aspect_ratio"] = "true" if preserve_aspect_ratio else "false"
        query_params["jpeg_quality"] = str(int(jpeg_quality))
        return self._request("GET", "/capture/viewport", query=query_params, allow_http_error_json=True)

    def get_events(
        self,
        *,
        session_id: Optional[str] = None,
        type_filter: Optional[str] = None,
        limit: Optional[int] = None,
        after_sequence: Optional[int] = None,
    ) -> JsonObject:
        query = self._build_query(session_id=session_id)
        if type_filter:
            query["type"] = type_filter
        if limit is not None:
            query["limit"] = str(int(limit))
        if after_sequence is not None:
            query["after_sequence"] = str(self._coerce_sequence_id(after_sequence, 0))
        return self._request("GET", "/events", query=query)

    def wait_for_event(
        self,
        *,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        predicate: Optional[Predicate] = None,
        timeout: float = 10.0,
        poll_interval: float = 0.25,
        type_filter: Optional[str] = None,
        limit: Optional[int] = None,
        after_sequence: Optional[int] = None,
    ) -> Mapping[str, Any]:
        resolved_session_id = self._resolve_session_id(session_id)
        deadline = time.monotonic() + timeout
        event_filter = type_filter or event_type
        cursor = self._coerce_sequence_id(after_sequence, 0)

        try:
            ws_outcome = self._wait_for_event_via_websocket(
                session_id=resolved_session_id,
                event_type=event_type,
                event_filter=event_filter,
                predicate=predicate,
                deadline=deadline,
                after_sequence=cursor,
            )
            cursor = max(cursor, ws_outcome.cursor)
            if ws_outcome.event is not None:
                return ws_outcome.event
            if ws_outcome.timed_out:
                raise UnrealTestClientTimeoutError(
                    f"Timed out waiting for event after {timeout} seconds."
                )
        except _WebSocketTransportError as exc:
            cursor = max(cursor, exc.cursor)

        while True:
            events_payload = self.get_events(
                session_id=resolved_session_id,
                type_filter=event_filter,
                limit=limit,
                after_sequence=cursor if cursor > 0 else None,
            )
            events = events_payload.get("events", [])
            if isinstance(events, list):
                for event in events:
                    if not isinstance(event, Mapping):
                        continue
                    if event_type and str(event.get("type", "")) != event_type:
                        continue
                    if predicate is not None and not predicate(event):
                        continue
                    return event

            cursor = max(cursor, self._coerce_sequence_id(events_payload.get("last_sequence"), cursor))

            if time.monotonic() >= deadline:
                raise UnrealTestClientTimeoutError(
                    f"Timed out waiting for event after {timeout} seconds."
                )

            time.sleep(max(0.0, poll_interval))

    def _wait_for_event_via_websocket(
        self,
        *,
        session_id: str,
        event_type: Optional[str],
        event_filter: Optional[str],
        predicate: Optional[Predicate],
        deadline: float,
        after_sequence: int,
    ) -> _WebSocketWaitOutcome:
        endpoint = self._get_websocket_endpoint()
        if endpoint is None:
            raise _WebSocketTransportError("websocket endpoint unavailable", cursor=after_sequence)

        cursor = after_sequence
        try:
            with _MinimalWebSocketClient(endpoint, timeout=self._config.timeout) as websocket:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return _WebSocketWaitOutcome(event=None, cursor=cursor, timed_out=True)

                    try:
                        event = websocket.recv_json(deadline=deadline)
                    except json.JSONDecodeError as exc:
                        raise _WebSocketTransportError(f"invalid websocket event payload: {exc}", cursor=cursor) from exc
                    except (ConnectionError, OSError, ValueError, ssl.SSLError) as exc:
                        raise _WebSocketTransportError(f"websocket receive failed: {exc}", cursor=cursor) from exc

                    if event is None:
                        continue

                    event_session_id = str(event.get("session_id", ""))
                    if event_session_id != session_id:
                        continue

                    event_sequence = self._coerce_sequence_id(event.get("sequence_id"), cursor)
                    if event_sequence <= cursor:
                        continue
                    cursor = event_sequence

                    if event_filter and str(event.get("type", "")) != event_filter:
                        continue
                    if event_type and str(event.get("type", "")) != event_type:
                        continue
                    if predicate is not None and not predicate(event):
                        continue
                    return _WebSocketWaitOutcome(event=event, cursor=cursor, timed_out=False)
        except _WebSocketTransportError:
            raise
        except (OSError, ValueError, ssl.SSLError) as exc:
            raise _WebSocketTransportError(f"websocket connection failed: {exc}", cursor=cursor) from exc

    def _get_websocket_endpoint(self) -> Optional[_WebSocketEndpoint]:
        capabilities = self._capabilities_cache
        if capabilities is None:
            try:
                capabilities = self.get_capabilities()
            except UnrealTestClientError:
                return None

        websocket_url = capabilities.get("events_websocket_url")
        if not isinstance(websocket_url, str) or not websocket_url:
            return None

        parsed = parse.urlsplit(websocket_url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            return None

        resource = parsed.path or "/"
        if parsed.query:
            resource = f"{resource}?{parsed.query}"

        return _WebSocketEndpoint(
            url=websocket_url,
            host=parsed.hostname,
            port=parsed.port or (443 if parsed.scheme == "wss" else 80),
            resource=resource,
            secure=parsed.scheme == "wss",
        )

    def _resolve_session_id(self, session_id: Optional[str]) -> str:
        resolved = session_id or self._session_id
        if not resolved:
            raise UnrealTestClientError("session_id is required. Call start_session() first or pass session_id explicitly.")
        return resolved

    def _build_query(self, **params: Optional[Any]) -> Dict[str, str]:
        query: Dict[str, str] = {}
        resolved_session_id = params.pop("session_id", None)
        if resolved_session_id is None:
            resolved_session_id = self._session_id
        if resolved_session_id:
            query["session_id"] = str(resolved_session_id)

        for key, value in params.items():
            if value is None:
                continue
            query[key] = str(value)
        return query

    def _append_optional_number(self, query: Dict[str, str], key: str, value: Optional[float]) -> None:
        if value is not None:
            query[key] = str(value)

    def _append_optional_bool(self, query: Dict[str, str], key: str, value: Optional[bool]) -> None:
        if value is not None:
            query[key] = "true" if value else "false"

    def _coerce_sequence_id(self, value: Any, fallback: int) -> int:
        if isinstance(value, bool):
            return fallback
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else fallback
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return fallback
        return fallback

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, str]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        allow_http_error_json: bool = False,
    ) -> JsonObject:
        url = self._build_url(path, query=query)
        body_bytes = None
        headers = {"Accept": "application/json"}

        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        last_error: Optional[Exception] = None
        for attempt in range(self._config.retry_attempts + 1):
            try:
                req = request.Request(url, data=body_bytes, headers=headers, method=method)
                with request.urlopen(req, timeout=self._config.timeout) as response:
                    payload = response.read().decode("utf-8")
                    if not payload:
                        return {}
                    return json.loads(payload)
            except error.HTTPError as exc:
                last_error = exc
                body_text = ""
                parsed_body: Optional[JsonObject] = None
                try:
                    body_text = exc.read().decode("utf-8", errors="replace")
                    if body_text.strip():
                        parsed = json.loads(body_text)
                        if isinstance(parsed, dict):
                            parsed_body = parsed
                except Exception:  # noqa: BLE001
                    pass

                if allow_http_error_json and parsed_body is not None:
                    return parsed_body

                if exc.code < 500 and exc.code != 429:
                    body_summary = body_text.strip().replace("\r", " ").replace("\n", " ")
                    if len(body_summary) > 300:
                        body_summary = f"{body_summary[:300]}..."
                    if body_summary:
                        raise UnrealTestClientError(
                            f"HTTP {exc.code} calling {method} {path}: {exc.reason} | body={body_summary}"
                        ) from exc
                    raise UnrealTestClientError(f"HTTP {exc.code} calling {method} {path}: {exc.reason}") from exc
            except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc

            if attempt < self._config.retry_attempts:
                time.sleep(self._config.retry_backoff * (attempt + 1))

        raise UnrealTestClientError(f"Request failed after retries: {method} {path}") from last_error

    def _build_url(self, path: str, *, query: Optional[Mapping[str, str]] = None) -> str:
        base = f"{self._base_url}{path}"
        if not query:
            return base
        return f"{base}?{parse.urlencode(dict(query))}"
