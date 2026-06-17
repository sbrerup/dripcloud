#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import ssl
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MANAGED_BY = "dripcraft-portal"
SERVICE_SELECTOR_LABEL = "app.kubernetes.io/name"
SERVICE_SELECTOR_VALUE = "crafty"
SERVER_ID_LABEL = "dripcloud.io/crafty-server-id"
SERVER_HOSTNAME_LABEL = "dripcloud.io/hostname"
SERVER_NAME_ANNOTATION = "dripcloud.io/crafty-server-name"
TARGET_PORT_ANNOTATION = "dripcloud.io/target-port"


class PortalError(Exception):
    status = 500
    code = "PORTAL_ERROR"

    def __init__(self, message: str, *, details: Any = None, status: int | None = None):
        super().__init__(message)
        self.details = details
        if status is not None:
            self.status = status


class UpstreamError(PortalError):
    code = "UPSTREAM_ERROR"


class ValidationError(PortalError):
    status = 400
    code = "VALIDATION_ERROR"


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def read_namespace(default: str = "dripcraft") -> str:
    value = os.getenv("POD_NAMESPACE")
    if value:
        return value
    path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return default


def sanitize_hostname(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        raise ValidationError("Hostname cannot be empty after sanitizing.")
    if len(value) > 50:
        value = value[:50].rstrip("-")
    if not re.match(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", value):
        raise ValidationError("Hostname must contain only letters, numbers, and dashes.")
    return value


def sanitize_service_name(hostname: str) -> str:
    name = f"minecraft-{sanitize_hostname(hostname)}"
    if len(name) > 63:
        name = name[:63].rstrip("-")
    return name


def clean_server_name(value: str) -> str:
    value = value.strip()
    if len(value) < 2:
        raise ValidationError("Server name must be at least two characters.")
    if re.search(r"[/\\#]", value):
        raise ValidationError("Server name cannot contain slash, backslash, or #.")
    return value


def parse_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValidationError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def extract_server_id(server: dict[str, Any]) -> str | None:
    for key in ("server_id", "server_uuid", "id", "uuid"):
        value = server.get(key)
        if value:
            return str(value)
    return None


def extract_server_name(server: dict[str, Any]) -> str:
    for key in ("server_name", "name", "friendly_name"):
        value = server.get(key)
        if value:
            return str(value)
    server_id = extract_server_id(server)
    return server_id or "unknown"


def extract_server_port(server: dict[str, Any]) -> int | None:
    for key in ("server_port", "port"):
        value = server.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    monitoring = server.get("minecraft_java_monitoring_data")
    if isinstance(monitoring, dict):
        value = monitoring.get("port")
        if isinstance(value, int):
            return value
    return None


def fqdn(hostname: str, tailnet_domain: str) -> str:
    if not tailnet_domain:
        return f"{hostname}.<tailnet>.ts.net"
    return f"{hostname}.{tailnet_domain.strip('.')}"


@dataclass(frozen=True)
class Config:
    bind_host: str
    bind_port: int
    namespace: str
    crafty_base_url: str
    crafty_panel_url: str
    crafty_api_token: str | None
    crafty_username: str | None
    crafty_password: str | None
    crafty_tls_verify: bool
    tailnet_domain: str
    port_range_start: int
    port_range_end: int
    service_external_port: int
    default_category: str
    default_jar_type: str
    default_minecraft_version: str
    default_mem_min: int
    default_mem_max: int
    portal_token: str | None
    auto_redirect: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            bind_host=os.getenv("BIND_HOST", "0.0.0.0"),
            bind_port=int_env("PORT", 8080),
            namespace=read_namespace(),
            crafty_base_url=os.getenv("CRAFTY_BASE_URL", "https://crafty-headless:8443").rstrip("/"),
            crafty_panel_url=os.getenv("CRAFTY_PANEL_URL", "https://10.1.2.250:8443").rstrip("/"),
            crafty_api_token=os.getenv("CRAFTY_API_TOKEN") or None,
            crafty_username=os.getenv("CRAFTY_USERNAME") or None,
            crafty_password=os.getenv("CRAFTY_PASSWORD") or None,
            crafty_tls_verify=bool_env("CRAFTY_TLS_VERIFY", False),
            tailnet_domain=os.getenv("TAILSCALE_DOMAIN", "").strip().strip("."),
            port_range_start=int_env("PORT_RANGE_START", 25565),
            port_range_end=int_env("PORT_RANGE_END", 25585),
            service_external_port=int_env("SERVICE_EXTERNAL_PORT", 25565),
            default_category=os.getenv("DEFAULT_JAR_CATEGORY", "Mc_java_servers"),
            default_jar_type=os.getenv("DEFAULT_JAR_TYPE", "Paper"),
            default_minecraft_version=os.getenv("DEFAULT_MC_VERSION", ""),
            default_mem_min=int_env("DEFAULT_MEM_MIN", 1),
            default_mem_max=int_env("DEFAULT_MEM_MAX", 4),
            portal_token=os.getenv("PORTAL_TOKEN") or None,
            auto_redirect=bool_env("AUTO_REDIRECT_TO_CRAFTY", True),
        )

    @property
    def crafty_configured(self) -> bool:
        return bool(self.crafty_api_token or (self.crafty_username and self.crafty_password))


class JsonHttpClient:
    def __init__(self, tls_verify: bool = True, bearer_token: str | None = None):
        self.tls_verify = tls_verify
        self.bearer_token = bearer_token

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        content_type: str = "application/json",
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
            **(headers or {}),
        }
        data = None
        if body is not None:
            request_headers["Content-Type"] = content_type
            data = json.dumps(body).encode("utf-8")
        if self.bearer_token:
            request_headers["Authorization"] = f"Bearer {self.bearer_token}"

        context = None
        if url.startswith("https://") and not self.tls_verify:
            context = ssl._create_unverified_context()

        request = urllib.request.Request(
            url,
            data=data,
            headers=request_headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            raise UpstreamError(
                f"{method.upper()} {url} failed with HTTP {exc.code}.",
                details=parsed,
                status=502,
            ) from exc
        except urllib.error.URLError as exc:
            raise UpstreamError(
                f"{method.upper()} {url} failed: {exc.reason}",
                status=502,
            ) from exc


class CraftyClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = JsonHttpClient(config.crafty_tls_verify, config.crafty_api_token)
        self.session_token: str | None = None
        self.session_token_at = 0.0

    def _token(self) -> str | None:
        if self.config.crafty_api_token:
            return self.config.crafty_api_token
        if not self.config.crafty_username or not self.config.crafty_password:
            return None
        if self.session_token and time.monotonic() - self.session_token_at < 3600:
            return self.session_token
        payload = {
            "username": self.config.crafty_username,
            "password": self.config.crafty_password,
        }
        response = self.client.request(
            "POST",
            f"{self.config.crafty_base_url}/api/v2/auth/login",
            body=payload,
        )
        token = (((response or {}).get("data") or {}).get("token"))
        if not token:
            raise UpstreamError("Crafty login did not return a token.", details=response, status=502)
        self.session_token = str(token)
        self.session_token_at = time.monotonic()
        return self.session_token

    def request(self, method: str, path: str, body: Any = None) -> Any:
        token = self._token()
        if not token:
            raise PortalError("Crafty credentials are not configured.", status=503)
        client = JsonHttpClient(self.config.crafty_tls_verify, token)
        return client.request(method, f"{self.config.crafty_base_url}{path}", body=body)

    def list_servers(self) -> list[dict[str, Any]]:
        response = self.request("GET", "/api/v2/servers")
        data = (response or {}).get("data", [])
        if not isinstance(data, list):
            raise UpstreamError("Crafty returned an unexpected server list.", details=response, status=502)
        servers: list[dict[str, Any]] = []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            server = dict(raw)
            if extract_server_id(server) and extract_server_port(server) is None:
                try:
                    detail = self.get_server(extract_server_id(server) or "")
                    server.update(detail)
                except PortalError:
                    pass
            servers.append(normalize_server(server))
        return servers

    def get_server(self, server_id: str) -> dict[str, Any]:
        response = self.request("GET", f"/api/v2/servers/{urllib.parse.quote(server_id)}")
        data = (response or {}).get("data")
        if not isinstance(data, dict):
            raise UpstreamError("Crafty returned an unexpected server detail.", details=response, status=502)
        return data

    def create_java_server(self, request: dict[str, Any], port: int) -> str:
        name = clean_server_name(str(request.get("name", "")))
        jar_type = str(request.get("jarType") or self.config.default_jar_type).strip()
        category = str(request.get("category") or self.config.default_category).strip()
        version = str(request.get("version") or self.config.default_minecraft_version).strip()
        if not version:
            raise ValidationError("Minecraft version is required.")
        if not jar_type:
            raise ValidationError("Server JAR type is required.")
        mem_min = parse_int(request.get("memMin", self.config.default_mem_min), "Minimum memory", 1, 64)
        mem_max = parse_int(request.get("memMax", self.config.default_mem_max), "Maximum memory", mem_min, 64)
        agree_to_eula = bool(request.get("agreeToEula"))
        if not agree_to_eula:
            raise ValidationError("You must confirm Minecraft EULA acceptance.")

        payload = {
            "name": name,
            "monitoring_type": "minecraft_java",
            "create_type": "minecraft_java",
            "autostart": bool(request.get("autostart", True)),
            "autostart_delay": parse_int(request.get("autostartDelay", 10), "Autostart delay", 0, 3600),
            "crashdetection": bool(request.get("crashDetection", True)),
            "stop_command": "",
            "log_location": "",
            "minecraft_java_monitoring_data": {
                "host": "127.0.0.1",
                "port": port,
            },
            "minecraft_java_create_data": {
                "create_type": "download_jar",
                "download_jar_create_data": {
                    "category": category,
                    "type": jar_type,
                    "version": version,
                    "mem_min": mem_min,
                    "mem_max": mem_max,
                    "server_properties_port": port,
                    "agree_to_eula": agree_to_eula,
                },
            },
        }
        response = self.request("POST", "/api/v2/servers", payload)
        data = (response or {}).get("data") or {}
        server_id = data.get("new_server_id") or data.get("new_server_uuid")
        if not server_id:
            raise UpstreamError("Crafty created a server but did not return its id.", details=response, status=502)
        return str(server_id)

    def delete_server(self, server_id: str, remove_files: bool) -> None:
        files = "true" if remove_files else "false"
        self.request("DELETE", f"/api/v2/servers/{urllib.parse.quote(server_id)}?files={files}")


class KubernetesClient:
    def __init__(self, namespace: str):
        self.namespace = namespace
        self.token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        self.ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
        self.base_url = f"https://{host}:{port}"

    @property
    def available(self) -> bool:
        return self.token_path.exists()

    def _context(self) -> ssl.SSLContext:
        if self.ca_path.exists():
            return ssl.create_default_context(cafile=str(self.ca_path))
        return ssl._create_unverified_context()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        content_type: str = "application/json",
        expected_not_found: bool = False,
    ) -> Any:
        if not self.available:
            raise PortalError("Kubernetes service account token is not available.", status=503)
        token = self.token_path.read_text(encoding="utf-8").strip()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = content_type
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=20, context=self._context()) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if expected_not_found and exc.code == 404:
                return None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            raise UpstreamError(
                f"Kubernetes API {method.upper()} {path} failed with HTTP {exc.code}.",
                details=parsed,
                status=502,
            ) from exc
        except urllib.error.URLError as exc:
            raise UpstreamError(f"Kubernetes API request failed: {exc.reason}", status=502) from exc

    def list_managed_services(self) -> list[dict[str, Any]]:
        selector = urllib.parse.urlencode({"labelSelector": f"app.kubernetes.io/managed-by={MANAGED_BY}"})
        response = self.request("GET", f"/api/v1/namespaces/{self.namespace}/services?{selector}")
        items = (response or {}).get("items", [])
        if not isinstance(items, list):
            return []
        return items

    def service_for_server(self, server_id: str) -> dict[str, Any] | None:
        for service in self.list_managed_services():
            labels = ((service.get("metadata") or {}).get("labels") or {})
            if labels.get(SERVER_ID_LABEL) == server_id:
                return service
        return None

    def create_or_update_service(
        self,
        *,
        server_id: str,
        server_name: str,
        hostname: str,
        target_port: int,
        external_port: int,
    ) -> dict[str, Any]:
        service_name = sanitize_service_name(hostname)
        manifest = build_service_manifest(
            name=service_name,
            namespace=self.namespace,
            server_id=server_id,
            server_name=server_name,
            hostname=hostname,
            target_port=target_port,
            external_port=external_port,
        )
        path = f"/api/v1/namespaces/{self.namespace}/services/{service_name}"
        existing = self.request("GET", path, expected_not_found=True)
        if existing:
            patch = {
                "metadata": {
                    "annotations": manifest["metadata"]["annotations"],
                    "labels": manifest["metadata"]["labels"],
                },
                "spec": manifest["spec"],
            }
            return self.request(
                "PATCH",
                path,
                body=patch,
                content_type="application/merge-patch+json",
            )
        return self.request("POST", f"/api/v1/namespaces/{self.namespace}/services", body=manifest)

    def delete_service_for_server(self, server_id: str) -> bool:
        service = self.service_for_server(server_id)
        if not service:
            return False
        name = ((service.get("metadata") or {}).get("name"))
        if not name:
            return False
        self.request("DELETE", f"/api/v1/namespaces/{self.namespace}/services/{name}")
        return True


def normalize_server(server: dict[str, Any]) -> dict[str, Any]:
    server_id = extract_server_id(server)
    return {
        "id": server_id,
        "name": extract_server_name(server),
        "port": extract_server_port(server),
        "raw": server,
    }


def build_service_manifest(
    *,
    name: str,
    namespace: str,
    server_id: str,
    server_name: str,
    hostname: str,
    target_port: int,
    external_port: int,
) -> dict[str, Any]:
    safe_hostname = sanitize_hostname(hostname)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "annotations": {
                "tailscale.com/hostname": safe_hostname,
                SERVER_NAME_ANNOTATION: server_name,
                TARGET_PORT_ANNOTATION: str(target_port),
            },
            "labels": {
                "app.kubernetes.io/name": "minecraft",
                "app.kubernetes.io/managed-by": MANAGED_BY,
                SERVER_ID_LABEL: server_id,
                SERVER_HOSTNAME_LABEL: safe_hostname,
            },
        },
        "spec": {
            "type": "LoadBalancer",
            "loadBalancerClass": "tailscale",
            "selector": {
                SERVICE_SELECTOR_LABEL: SERVICE_SELECTOR_VALUE,
            },
            "ports": [
                {
                    "name": "minecraft",
                    "port": external_port,
                    "targetPort": target_port,
                    "protocol": "TCP",
                }
            ],
        },
    }


def used_ports(servers: list[dict[str, Any]], services: list[dict[str, Any]]) -> set[int]:
    ports: set[int] = set()
    for server in servers:
        port = server.get("port")
        if isinstance(port, int):
            ports.add(port)
    for service in services:
        for port_spec in ((service.get("spec") or {}).get("ports") or []):
            target = port_spec.get("targetPort")
            if isinstance(target, int):
                ports.add(target)
            elif isinstance(target, str) and target.isdigit():
                ports.add(int(target))
    return ports


def find_created_server(
    before_servers: list[dict[str, Any]],
    after_servers: list[dict[str, Any]],
    name: str,
    port: int,
) -> dict[str, Any] | None:
    before_ids = {server.get("id") for server in before_servers if server.get("id")}
    for server in after_servers:
        if server.get("id") in before_ids:
            continue
        if server.get("name") == name and server.get("port") == port:
            return server
    return None


def next_free_port(start: int, end: int, taken: set[int]) -> int:
    for port in range(start, end + 1):
        if port not in taken:
            return port
    raise ValidationError(f"No free Minecraft ports in range {start}-{end}.")


def unique_hostname(name: str, used_hostnames: set[str], server_id: str) -> str:
    base = sanitize_hostname(name)
    if base not in used_hostnames:
        used_hostnames.add(base)
        return base

    suffix = re.sub(r"[^a-z0-9]", "", server_id.lower())[:8] or "server"
    max_base_length = max(1, 50 - len(suffix) - 1)
    candidate = f"{base[:max_base_length].rstrip('-')}-{suffix}"
    if candidate not in used_hostnames:
        used_hostnames.add(candidate)
        return candidate

    for index in range(2, 100):
        index_suffix = f"{suffix}-{index}"
        max_index_base_length = max(1, 50 - len(index_suffix) - 1)
        candidate = f"{base[:max_index_base_length].rstrip('-')}-{index_suffix}"
        if candidate not in used_hostnames:
            used_hostnames.add(candidate)
            return candidate

    raise ValidationError(f"Could not derive a unique hostname for {name}.")


def service_summary(service: dict[str, Any], tailnet_domain: str) -> dict[str, Any]:
    metadata = service.get("metadata") or {}
    labels = metadata.get("labels") or {}
    annotations = metadata.get("annotations") or {}
    spec = service.get("spec") or {}
    status = service.get("status") or {}
    hostname = annotations.get("tailscale.com/hostname") or labels.get(SERVER_HOSTNAME_LABEL) or ""
    ports = spec.get("ports") or []
    target_port = None
    external_port = None
    if ports:
        target_port = ports[0].get("targetPort")
        external_port = ports[0].get("port")
    ingress = (status.get("loadBalancer") or {}).get("ingress") or []
    external_ip = None
    if ingress:
        external_ip = ingress[0].get("ip") or ingress[0].get("hostname")
    return {
        "name": metadata.get("name"),
        "serverId": labels.get(SERVER_ID_LABEL),
        "hostname": hostname,
        "fqdn": fqdn(hostname, tailnet_domain) if hostname else None,
        "targetPort": target_port,
        "externalPort": external_port,
        "externalIp": external_ip,
    }


class App:
    def __init__(self, config: Config):
        self.config = config
        self.crafty = CraftyClient(config)
        self.kube = KubernetesClient(config.namespace)

    def list_state(self) -> dict[str, Any]:
        servers = self.crafty.list_servers() if self.config.crafty_configured else []
        services = self.kube.list_managed_services() if self.kube.available else []
        exposure_by_server = {
            summary.get("serverId"): summary
            for summary in (service_summary(service, self.config.tailnet_domain) for service in services)
            if summary.get("serverId")
        }
        for server in servers:
            server["exposure"] = exposure_by_server.get(server.get("id"))
        return {
            "servers": servers,
            "exposures": list(exposure_by_server.values()),
            "craftyConfigured": self.config.crafty_configured,
            "kubernetesConfigured": self.kube.available,
        }

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.crafty_configured:
            raise PortalError("Crafty credentials are not configured.", status=503)
        server_name = clean_server_name(str(payload.get("name", "")))
        hostname = sanitize_hostname(str(payload.get("hostname") or payload.get("name") or ""))
        servers = self.crafty.list_servers()
        services = self.kube.list_managed_services()
        requested_port = payload.get("port")
        if requested_port:
            port = parse_int(requested_port, "Port", self.config.port_range_start, self.config.port_range_end)
            if port in used_ports(servers, services):
                raise ValidationError(f"Port {port} is already in use.")
        else:
            port = next_free_port(
                self.config.port_range_start,
                self.config.port_range_end,
                used_ports(servers, services),
            )
        try:
            server_id = self.crafty.create_java_server(payload, port)
        except UpstreamError:
            time.sleep(2)
            created_server = find_created_server(
                servers,
                self.crafty.list_servers(),
                server_name,
                port,
            )
            if not created_server or not created_server.get("id"):
                raise
            server_id = str(created_server["id"])
        service = self.kube.create_or_update_service(
            server_id=server_id,
            server_name=server_name,
            hostname=hostname,
            target_port=port,
            external_port=self.config.service_external_port,
        )
        return {
            "serverId": server_id,
            "name": server_name,
            "port": port,
            "exposure": service_summary(service, self.config.tailnet_domain),
            "craftyPanelUrl": self.config.crafty_panel_url,
            "autoRedirect": self.config.auto_redirect,
        }

    def expose_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        server_id = str(payload.get("serverId") or "")
        if not server_id:
            raise ValidationError("Server id is required.")
        server_name = clean_server_name(str(payload.get("name") or server_id))
        hostname = sanitize_hostname(str(payload.get("hostname") or server_name))
        target_port = parse_int(payload.get("port"), "Target port", 1, 65535)
        service = self.kube.create_or_update_service(
            server_id=server_id,
            server_name=server_name,
            hostname=hostname,
            target_port=target_port,
            external_port=self.config.service_external_port,
        )
        return {
            "exposure": service_summary(service, self.config.tailnet_domain),
        }

    def sync_existing_servers(self) -> dict[str, Any]:
        if not self.config.crafty_configured:
            raise PortalError("Crafty credentials are not configured.", status=503)
        servers = self.crafty.list_servers()
        services = self.kube.list_managed_services()
        existing_services_by_server = {}
        used_service_hostnames: set[str] = set()
        for service in services:
            summary = service_summary(service, self.config.tailnet_domain)
            server_id = summary.get("serverId")
            if server_id:
                existing_services_by_server[server_id] = service
            hostname = summary.get("hostname")
            if hostname:
                used_service_hostnames.add(str(hostname))

        created = []
        skipped = []
        for server in servers:
            server_id = server.get("id")
            server_name = server.get("name") or server_id or "server"
            port = server.get("port")
            if not server_id:
                skipped.append({"name": server_name, "reason": "missing_server_id"})
                continue
            if server_id in existing_services_by_server:
                skipped.append({"serverId": server_id, "name": server_name, "reason": "already_exposed"})
                continue
            if not isinstance(port, int):
                skipped.append({"serverId": server_id, "name": server_name, "reason": "missing_port"})
                continue

            hostname = unique_hostname(str(server_name), used_service_hostnames, str(server_id))
            service = self.kube.create_or_update_service(
                server_id=str(server_id),
                server_name=str(server_name),
                hostname=hostname,
                target_port=port,
                external_port=self.config.service_external_port,
            )
            created.append(
                {
                    "serverId": server_id,
                    "name": server_name,
                    "port": port,
                    "exposure": service_summary(service, self.config.tailnet_domain),
                }
            )

        return {
            "created": created,
            "skipped": skipped,
            "createdCount": len(created),
            "skippedCount": len(skipped),
        }

    def delete_server(self, server_id: str, remove_files: bool) -> dict[str, Any]:
        if not server_id:
            raise ValidationError("Server id is required.")
        self.crafty.delete_server(server_id, remove_files)
        removed_exposure = self.kube.delete_service_for_server(server_id)
        return {
            "serverId": server_id,
            "removedExposure": removed_exposure,
        }

    def delete_exposure(self, server_id: str) -> dict[str, Any]:
        if not server_id:
            raise ValidationError("Server id is required.")
        removed = self.kube.delete_service_for_server(server_id)
        return {
            "serverId": server_id,
            "removed": removed,
        }


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        return {}
    raw = handler.rfile.read(content_length)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError("Request body must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("Request body must be a JSON object.")
    return parsed


class PortalHandler(BaseHTTPRequestHandler):
    app: App
    static_root: Path

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def do_DELETE(self) -> None:
        self.handle_request("DELETE")

    def handle_request(self, method: str) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if path.startswith("/api/"):
                self.require_token(path)
                self.handle_api(method, path, query)
                return
            if path == "/healthz":
                json_response(self, 200, {"status": "ok"})
                return
            self.serve_static(path)
        except PortalError as exc:
            print(
                json.dumps(
                    {
                        "level": "error",
                        "path": self.path,
                        "error": exc.code,
                        "message": str(exc),
                        "details": exc.details,
                    },
                    separators=(",", ":"),
                )
            )
            json_response(
                self,
                exc.status,
                {
                    "status": "error",
                    "error": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                },
            )
        except Exception as exc:
            traceback.print_exc()
            json_response(
                self,
                500,
                {
                    "status": "error",
                    "error": "UNHANDLED_ERROR",
                    "message": str(exc),
                },
            )

    def require_token(self, path: str) -> None:
        if path == "/api/config":
            return
        expected = self.app.config.portal_token
        if not expected:
            return
        provided = self.headers.get("X-Portal-Token") or ""
        if provided != expected:
            raise PortalError("Portal token is required.", status=401)

    def handle_api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        if method == "GET" and path == "/api/config":
            config = self.app.config
            json_response(
                self,
                200,
                {
                    "status": "ok",
                    "data": {
                        "craftyPanelUrl": config.crafty_panel_url,
                        "craftyConfigured": config.crafty_configured,
                        "kubernetesConfigured": self.app.kube.available,
                        "tailnetDomain": config.tailnet_domain,
                        "portRangeStart": config.port_range_start,
                        "portRangeEnd": config.port_range_end,
                        "serviceExternalPort": config.service_external_port,
                        "defaultCategory": config.default_category,
                        "defaultJarType": config.default_jar_type,
                        "defaultMinecraftVersion": config.default_minecraft_version,
                        "defaultMemMin": config.default_mem_min,
                        "defaultMemMax": config.default_mem_max,
                        "authRequired": bool(config.portal_token),
                        "autoRedirect": config.auto_redirect,
                    },
                },
            )
            return
        if method == "GET" and path == "/api/servers":
            json_response(self, 200, {"status": "ok", "data": self.app.list_state()})
            return
        if method == "POST" and path == "/api/servers":
            json_response(self, 201, {"status": "ok", "data": self.app.create_server(read_json(self))})
            return
        if method == "POST" and path == "/api/exposures":
            json_response(self, 201, {"status": "ok", "data": self.app.expose_server(read_json(self))})
            return
        if method == "POST" and path == "/api/sync":
            json_response(self, 200, {"status": "ok", "data": self.app.sync_existing_servers()})
            return
        server_delete_match = re.match(r"^/api/servers/([^/]+)$", path)
        if method == "DELETE" and server_delete_match:
            server_id = urllib.parse.unquote(server_delete_match.group(1))
            remove_files = (query.get("files") or ["false"])[0].lower() == "true"
            json_response(
                self,
                200,
                {"status": "ok", "data": self.app.delete_server(server_id, remove_files)},
            )
            return
        exposure_delete_match = re.match(r"^/api/exposures/([^/]+)$", path)
        if method == "DELETE" and exposure_delete_match:
            server_id = urllib.parse.unquote(exposure_delete_match.group(1))
            json_response(
                self,
                200,
                {"status": "ok", "data": self.app.delete_exposure(server_id)},
            )
            return
        raise PortalError("Route not found.", status=404)

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            relative = "index.html"
        elif path.startswith("/static/"):
            relative = path.removeprefix("/static/")
        else:
            relative = path.lstrip("/")
        target = (self.static_root / relative).resolve()
        root = self.static_root.resolve()
        if not str(target).startswith(str(root)) or not target.exists() or not target.is_file():
            target = self.static_root / "index.html"
        content_type = "text/plain"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    config = Config.from_env()
    PortalHandler.app = App(config)
    PortalHandler.static_root = Path(__file__).parent / "static"
    server = ThreadingHTTPServer((config.bind_host, config.bind_port), PortalHandler)
    print(f"Dripcraft Portal listening on http://{config.bind_host}:{config.bind_port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
