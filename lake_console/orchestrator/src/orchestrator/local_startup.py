"""Local service readiness and launch, separate from Dagster definitions."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class StartupError(RuntimeError):
    """Safe operator-facing error; never contains driver messages or secrets."""


@dataclass(frozen=True)
class StartupPolicy:
    query_timeout: int = 10
    ready_timeout: int = 30
    start_timeout: int = 40
    poll_seconds: int = 1
    host: str = "127.0.0.1"
    port: int = 3000
    pool_overflow: int = 80
    live_poll_ms: int = 10000


@dataclass(frozen=True)
class Dependency:
    name: str
    kind: str
    host: str
    port: int
    connection: dict
    remedy: str


LOOPBACK = {"localhost", "127.0.0.1", "::1"}
PROJECT = Path(__file__).resolve().parents[2]
BIN = PROJECT.parent / "bin"
PG_HOME = Path("/opt/homebrew/var/postgresql@18")
BREW = Path("/opt/homebrew/bin/brew")
PG_BINARY = Path("/opt/homebrew/opt/postgresql@18/bin/postgres")


def configuration(environ, home):
    import yaml

    expected = home / ".goldenshare/dagster_home"
    instance_home = Path(environ.get("DAGSTER_HOME") or expected).expanduser()
    if instance_home.resolve() != expected.resolve():
        raise StartupError("DAGSTER_HOME必须是现有本机正式实例目录，禁止新建实例。")
    try:
        config = yaml.safe_load((instance_home / "dagster.yaml").read_text())
        url = config["storage"]["postgres"]["postgres_url"]
        if isinstance(url, dict) and set(url) == {"env"}:
            url = environ[url["env"]]
        if not isinstance(url, str):
            raise TypeError
        parsed = urlparse(url)
        if parsed.scheme != "postgresql" or parsed.hostname not in LOOPBACK:
            raise ValueError
        if parsed.port not in (None, 5432) or parsed.path != "/goldenshare_dagster":
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise StartupError(
            "现有dagster.yaml/PG连接配置无效；不会初始化数据库。"
        ) from exc
    dependencies = [
        Dependency(
            "本机 PostgreSQL",
            "pg",
            parsed.hostname,
            5432,
            {"url": url},
            "检查已安装的postgresql@18及现有实例配置",
        )
    ]
    for prefix, label in (
        ("CLICKHOUSE", "本机 ClickHouse"),
        ("PROD_CLICKHOUSE", "Prod ClickHouse隧道"),
    ):
        required = [
            f"{prefix}_{key}"
            for key in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE")
        ]
        missing = [
            key
            for key in required
            if key not in environ
            or (not environ[key].strip() and not key.endswith("_PASSWORD"))
        ]
        if missing:
            raise StartupError(
                "缺少环境变量：" + ", ".join(missing) + "；检查~/.bash_profile。"
            )
        try:
            port = int(environ[f"{prefix}_PORT"])
            host = environ[f"{prefix}_HOST"].strip()
            if host not in LOOPBACK or not 1 <= port <= 65535:
                raise ValueError
            if prefix == "CLICKHOUSE" and port != 9000:
                raise ValueError
            if prefix == "PROD_CLICKHOUSE" and port in (5432, 9000, 3000):
                raise ValueError
        except ValueError as exc:
            raise StartupError(f"{label}地址/端口不属于本机现有启动方式。") from exc
        connection = {
            key.lower(): environ[f"{prefix}_{key}"]
            for key in ("HOST", "USER", "PASSWORD", "DATABASE")
        }
        connection["port"] = port
        dependencies.append(
            Dependency(
                label, "ch", host, port, connection, "检查连接配置、认证及隧道日志"
            )
        )
    return instance_home, tuple(dependencies)


def run_probe(kind, connection):
    """Executed in a bounded child, never initializes storage or prints exceptions."""
    try:
        if kind == "pg":
            import psycopg2

            with (
                closing(
                    psycopg2.connect(
                        connection["url"],
                        connect_timeout=3,
                        options="-c default_transaction_read_only=on -c statement_timeout=3000",
                    )
                ) as conn,
                conn.cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT 1, to_regclass('public.runs'), "
                    "to_regclass('public.event_logs'), to_regclass('public.jobs')"
                )
                row = cursor.fetchone()
                return "ready" if row[0] == 1 and all(row[1:]) else "schema_missing"
        if kind == "ch":
            from clickhouse_driver import Client

            client = Client(**connection, connect_timeout=3, send_receive_timeout=3)
            try:
                rows = client.execute(
                    "SELECT 1 LIMIT 1",
                    settings={
                        "readonly": 1,
                        "max_execution_time": 3,
                        "max_rows_to_read": 1,
                        "max_bytes_to_read": 1024,
                        "max_result_rows": 1,
                    },
                )
                return "ready" if rows == [(1,)] else "query_failed"
            finally:
                client.disconnect()
        return "invalid_probe"
    except Exception:  # noqa: BLE001 -- Keep all driver/credential details inside the probe child.
        return "connection_or_auth_failed"


class Runtime:
    def __init__(self, policy, environ):
        self.policy, self.environ = policy, dict(environ)
        self.pending_tunnel = None

    @staticmethod
    def say(message):
        print(message, flush=True)

    @staticmethod
    def listening(host, port):
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except ConnectionRefusedError:
            return False
        except OSError as exc:
            raise StartupError(
                f"端口检查失败：{host}:{port}，先核对地址和权限。"
            ) from exc

    def probe(self, dependency, timeout=None):
        if not self.listening(dependency.host, dependency.port):
            return "absent"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "orchestrator.local_startup",
                    "--probe",
                    dependency.kind,
                ],
                input=json.dumps(dependency.connection),
                text=True,
                capture_output=True,
                cwd=PROJECT,
                env=self.environ,
                timeout=self.policy.query_timeout if timeout is None else timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "query_timeout"
        value = result.stdout.strip()
        return (
            value
            if result.returncode == 0
            and value
            in {"ready", "schema_missing", "query_failed", "connection_or_auth_failed"}
            else "query_failed"
        )

    def command(self, argv, environment=None):
        child = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment or self.environ,
            start_new_session=True,
        )
        try:
            child.communicate(timeout=self.policy.start_timeout)
            if child.returncode:
                raise StartupError(
                    f"依赖启动命令失败（退出码{child.returncode}），DG未启动。"
                )
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
            raise

    def start(self, dependency):
        self.say(f"[启动] {dependency.name}未监听，自动启动一次。")
        if dependency.kind == "pg":
            if (
                not BREW.is_file()
                or not PG_BINARY.is_file()
                or not (PG_HOME / "PG_VERSION").is_file()
            ):
                raise StartupError("缺少已安装的PG18或原数据目录；禁止安装/initdb。")
            if (PG_HOME / "PG_VERSION").read_text().strip() != "18":
                raise StartupError("PG_VERSION不为18；禁止升级或重建。")
            env = {
                **self.environ,
                "HOMEBREW_NO_AUTO_UPDATE": "1",
                "HOMEBREW_NO_INSTALL_FROM_API": "1",
            }
            self.command([str(BREW), "services", "start", "postgresql@18"], env)
        elif dependency.name == "本机 ClickHouse":
            self.command(["/bin/bash", str(BIN / "lake-clickhouse-start")])
        else:
            logs = Path.home() / ".goldenshare/dagster_logs"
            logs.mkdir(parents=True, exist_ok=True)
            env = {**self.environ, "PROD_CLICKHOUSE_TUNNEL_PORT": str(dependency.port)}
            with (logs / "lake-dg-start-tunnel.log").open("a") as log:
                self.pending_tunnel = subprocess.Popen(
                    ["/bin/bash", str(BIN / "lake-prod-clickhouse-tunnel"), "--batch"],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    env=env,
                    start_new_session=True,
                )

    def cleanup(self):
        if self.pending_tunnel is not None:
            child = self.pending_tunnel
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            self.pending_tunnel = None

    def ensure(self, dependency, check_only):
        self.say(f"[检查] {dependency.name} {dependency.host}:{dependency.port}")
        status = self.probe(dependency)
        if status == "ready":
            self.say(f"[通过] {dependency.name}查询就绪；复用现有服务。")
            return
        if status != "absent":
            raise StartupError(
                f"{dependency.name}端口已监听但查询未通过（{status}）；{dependency.remedy}，不自动重启。"
            )
        if check_only:
            raise StartupError(f"{dependency.name}未启动（只检查模式不会启动）。")
        self.start(dependency)
        deadline = time.monotonic() + self.policy.ready_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if (
                self.pending_tunnel is not None
                and self.pending_tunnel.poll() is not None
            ):
                raise StartupError(
                    "SSH隧道启动失败；检查SSH密钥/known_hosts及隧道日志。"
                )
            status = self.probe(
                dependency, timeout=min(self.policy.query_timeout, remaining)
            )
            if status == "ready":
                self.pending_tunnel = (
                    None  # Ready dependencies remain alive independently of DG.
                )
                self.say(f"[通过] {dependency.name}已启动并通过真实查询。")
                return
            if status != "absent":
                raise StartupError(
                    f"{dependency.name}启动后查询失败（{status}）；DG未启动。"
                )
            self.say(f"[等待] {dependency.name}尚未就绪。")
            time.sleep(self.policy.poll_seconds)
        raise StartupError(f"{dependency.name}就绪等待超时；DG未启动。")

    def warnings(self):
        import shutil

        from orchestrator.defs.duckdb_connection import DEFAULT_DUCKDB_TEMP_DIRECTORY
        from orchestrator.defs.health.lake_root import LAKE_ROOT_MIN_FREE_BYTES
        from orchestrator.defs.notifications.feishu import FEISHU_WEBHOOK_URL_ENV_VAR
        from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT

        root = Path(DEFAULT_LAKE_ROOT)
        directories = [root / layer for layer in ("raw", "silver", "gold")]
        directories += [Path(DEFAULT_LAKE_STAGING_ROOT), DEFAULT_DUCKDB_TEMP_DIRECTORY]
        if not Path("/Volumes/datasource").is_mount() or not all(
            p.is_dir() for p in directories
        ):
            self.say(
                "[警告] datasource挂载或Lake/staging/temp目录缺失；写湖仍由执行门禁阻断。"
            )
        elif shutil.disk_usage(root).free < LAKE_ROOT_MIN_FREE_BYTES:
            self.say("[警告] 外盘空间低于现有Lake健康门槛；启动不代替运行时写盘检查。")
        for name in ("TUSHARE_TOKEN", FEISHU_WEBHOOK_URL_ENV_VAR):
            if not self.environ.get(name, "").strip():
                self.say(f"[警告] {name}缺失，相关任务/通知可能失败。")

    def launch(self, instance_home, lock_fd):
        environ = {**self.environ, "DAGSTER_HOME": str(instance_home)}
        os.environ.update(environ)
        os.chdir(PROJECT)
        os.set_inheritable(lock_fd, True)
        self.say("[启动] 依赖就绪，启动DG webserver和daemon，http://127.0.0.1:3000")
        dg = PROJECT / ".venv/bin/dg"
        os.execv(
            str(dg),
            [
                str(dg),
                "dev",
                "--host",
                self.policy.host,
                "--port",
                str(self.policy.port),
                "--db-pool-max-overflow",
                str(self.policy.pool_overflow),
                "--live-data-poll-rate",
                str(self.policy.live_poll_ms),
            ],
        )


def prepare(runtime, dependencies, *, check_only):
    failures = []
    try:
        for dependency in dependencies:
            try:
                runtime.ensure(dependency, check_only)
            except StartupError as exc:
                if not check_only:
                    raise
                failures.append(str(exc))
        runtime.warnings()
        if failures:
            raise StartupError("；".join(failures))
    finally:
        runtime.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="自动启动现有PG/CH/隧道，通过查询后启动DG。"
    )
    parser.add_argument(
        "--check-only", action="store_true", help="只读检查，不启动服务或DG"
    )
    parser.add_argument("--probe", choices=("pg", "ch"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe:
        print(run_probe(args.probe, json.load(sys.stdin)))
        return 0
    runtime = Runtime(StartupPolicy(), os.environ)
    try:
        instance_home, dependencies = configuration(runtime.environ, Path.home())
        if args.check_only:
            prepare(runtime, dependencies, check_only=True)
            runtime.say("[完成] 依赖检查通过；未启动DG或修改服务状态。")
            return 0
        if runtime.listening(runtime.policy.host, runtime.policy.port):
            raise StartupError(
                "3000端口已有监听，DG可能已运行；不重复启动、不终止现有进程。"
            )
        with (instance_home / "lake-dg-start.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StartupError("另一个DG启动入口正在运行。") from exc
            prepare(runtime, dependencies, check_only=False)
            runtime.launch(instance_home, lock.fileno())
        return 0
    except KeyboardInterrupt:
        runtime.cleanup()
        runtime.say("[取消] 已停止本轮启动流程；现有/已就绪的PG、CH和隧道保留。")
        return 130
    except (StartupError, OSError, subprocess.TimeoutExpired) as exc:
        runtime.cleanup()
        detail = str(exc) if isinstance(exc, StartupError) else type(exc).__name__
        runtime.say(f"[失败] {detail}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
