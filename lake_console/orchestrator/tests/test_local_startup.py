"""Isolated startup checks; no real service, network, instance or Lake operations."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from orchestrator import local_startup as startup


def dependency(name="本机 PostgreSQL", kind="pg"):
    return startup.Dependency(
        name,
        kind,
        "127.0.0.1",
        5432,
        {"url": "postgresql://user:SECRET@localhost/goldenshare_dagster"},
        "核对配置",
    )


class StartupTests(unittest.TestCase):
    def runtime(self):
        r = startup.Runtime(startup.StartupPolicy(), {})
        r.say = Mock()
        r.warnings = Mock()
        r.cleanup = Mock()
        r.start = Mock()
        return r

    def test_ready_reuses_service(self):
        r = self.runtime()
        r.probe = Mock(return_value="ready")
        r.ensure(dependency(), False)
        r.start.assert_not_called()

    def test_absent_starts_once_and_queries_again(self):
        r = self.runtime()
        r.probe = Mock(side_effect=["absent", "absent", "ready"])
        with patch.object(startup.time, "sleep"):
            r.ensure(dependency(), False)
        r.start.assert_called_once()
        self.assertEqual(r.probe.call_count, 3)

    def test_check_only_never_starts(self):
        r = self.runtime()
        r.probe = Mock(return_value="absent")
        with self.assertRaises(startup.StartupError):
            r.ensure(dependency(), True)
        r.start.assert_not_called()

    def test_listening_bad_query_is_not_restarted(self):
        for result in ("connection_or_auth_failed", "schema_missing", "query_timeout"):
            r = self.runtime()
            r.probe = Mock(return_value=result)
            with self.assertRaises(startup.StartupError):
                r.ensure(dependency(), False)
            r.start.assert_not_called()

    def test_failed_post_start_query_blocks(self):
        r = self.runtime()
        r.probe = Mock(side_effect=["absent", "connection_or_auth_failed"])
        with self.assertRaises(startup.StartupError):
            startup.prepare(r, (dependency(),), check_only=False)
        r.cleanup.assert_called_once()

    def test_timeout_blocks(self):
        r = self.runtime()
        r.probe = Mock(return_value="absent")
        with (
            patch.object(startup.time, "monotonic", side_effect=[0, 31]),
            self.assertRaisesRegex(startup.StartupError, "超时"),
        ):
            r.ensure(dependency(), False)
        r.start.assert_called_once()

    def test_check_only_collects_all_failures(self):
        r = self.runtime()
        r.probe = Mock(return_value="absent")
        with self.assertRaises(startup.StartupError):
            startup.prepare(r, (dependency(), dependency("CH", "ch")), check_only=True)
        self.assertEqual(r.probe.call_count, 2)
        r.start.assert_not_called()

    def test_new_tunnel_exit_blocks(self):
        r = self.runtime()
        r.probe = Mock(return_value="absent")
        r.pending_tunnel = Mock()
        r.pending_tunnel.poll.return_value = 255
        with self.assertRaisesRegex(startup.StartupError, "SSH"):
            r.ensure(dependency("Prod", "ch"), False)

    def test_cancel_cleans_pending_tunnel(self):
        r = self.runtime()
        r.ensure = Mock(side_effect=KeyboardInterrupt)
        with self.assertRaises(KeyboardInterrupt):
            startup.prepare(r, (dependency(),), check_only=False)
        r.cleanup.assert_called_once()

    def test_probe_password_in_stdin_only(self):
        r = self.runtime()
        r.listening = Mock(return_value=True)
        with patch.object(
            startup.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="ready"),
        ) as run:
            self.assertEqual(r.probe(dependency()), "ready")
        self.assertNotIn("SECRET", str(run.call_args.args))
        self.assertIn("SECRET", run.call_args.kwargs["input"])
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_probe_hides_driver_output(self):
        r = self.runtime()
        r.listening = Mock(return_value=True)
        with patch.object(
            startup.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1, stdout="SECRET"),
        ):
            self.assertEqual(r.probe(dependency()), "query_failed")

    def test_probe_timeout_classified(self):
        r = self.runtime()
        r.listening = Mock(return_value=True)
        with patch.object(
            startup.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("probe", 10),
        ):
            self.assertEqual(r.probe(dependency()), "query_timeout")

    def test_refused_port_absent_but_permission_error_blocks(self):
        with patch.object(
            startup.socket, "create_connection", side_effect=ConnectionRefusedError
        ):
            self.assertFalse(startup.Runtime.listening("localhost", 5432))
        with (
            patch.object(
                startup.socket, "create_connection", side_effect=PermissionError
            ),
            self.assertRaises(startup.StartupError),
        ):
            startup.Runtime.listening("localhost", 5432)

    def test_pg_starts_only_existing_version(self):
        r = startup.Runtime(startup.StartupPolicy(), {})
        r.say = Mock()
        r.command = Mock()
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            version = data / "PG_VERSION"
            version.write_text("18")
            binary = data / "postgres"
            binary.touch()
            brew = data / "brew"
            brew.touch()
            with (
                patch.object(startup, "PG_HOME", data),
                patch.object(startup, "PG_BINARY", binary),
                patch.object(startup, "BREW", brew),
            ):
                r.start(dependency())
                command, environment = r.command.call_args.args
                self.assertEqual(
                    command, [str(brew), "services", "start", "postgresql@18"]
                )
                self.assertEqual(environment["HOMEBREW_NO_AUTO_UPDATE"], "1")
                version.write_text("17")
                with self.assertRaises(startup.StartupError):
                    r.start(dependency())
                version.unlink()
                with self.assertRaisesRegex(startup.StartupError, "initdb"):
                    r.start(dependency())
                self.assertEqual(r.command.call_count, 1)

    def test_local_ch_uses_existing_helper(self):
        r = startup.Runtime(startup.StartupPolicy(), {})
        r.say = Mock()
        r.command = Mock()
        r.start(dependency("本机 ClickHouse", "ch"))
        self.assertEqual(
            r.command.call_args.args[0],
            ["/bin/bash", str(startup.BIN / "lake-clickhouse-start")],
        )

    def test_new_tunnel_batch_cleanup_only_own_group(self):
        r = startup.Runtime(startup.StartupPolicy(), {})
        r.say = Mock()
        child = Mock(pid=12345)
        child.poll.return_value = None
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(startup.Path, "home", return_value=Path(temp)),
            patch.object(startup.subprocess, "Popen", return_value=child) as popen,
        ):
            r.start(dependency("Prod", "ch"))
            self.assertEqual(popen.call_args.args[0][-1], "--batch")
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
        with patch.object(startup.os, "killpg") as kill:
            r.cleanup()
            kill.assert_called_once_with(12345, startup.signal.SIGTERM)
        self.assertIsNone(r.pending_tunnel)

    def test_ready_tunnel_not_stopped(self):
        r = self.runtime()
        r.probe = Mock(side_effect=["absent", "ready"])
        r.pending_tunnel = Mock()
        r.pending_tunnel.poll.return_value = None
        r.ensure(dependency("Prod", "ch"), False)
        self.assertIsNone(r.pending_tunnel)

    def test_busy_port_main_does_not_start(self):
        r = self.runtime()
        r.listening = Mock(return_value=True)
        with (
            patch.object(startup, "Runtime", return_value=r),
            patch.object(
                startup, "configuration", return_value=(Path("/not_used"), ())
            ),
        ):
            self.assertEqual(startup.main([]), 1)
        r.start.assert_not_called()

    def test_check_only_no_lock_or_launch(self):
        r = self.runtime()
        r.ensure = Mock()
        r.launch = Mock()
        with (
            patch.object(startup, "Runtime", return_value=r),
            patch.object(
                startup,
                "configuration",
                return_value=(Path("/not_used"), (dependency(),)),
            ),
        ):
            self.assertEqual(startup.main(["--check-only"]), 0)
        r.launch.assert_not_called()
        r.start.assert_not_called()

    def test_lock_prevents_service_start(self):
        r = self.runtime()
        r.listening = Mock(return_value=False)
        r.launch = Mock()
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(startup, "Runtime", return_value=r),
            patch.object(
                startup, "configuration", return_value=(Path(temp), (dependency(),))
            ),
            patch.object(startup.fcntl, "flock", side_effect=BlockingIOError),
        ):
            self.assertEqual(startup.main([]), 1)
        r.start.assert_not_called()
        r.launch.assert_not_called()

    def test_launch_parameters_and_instance(self):
        r = startup.Runtime(startup.StartupPolicy(), {"A": "B"})
        r.say = Mock()
        with (
            patch.object(startup.os, "environ", {}),
            patch.object(startup.os, "chdir"),
            patch.object(startup.os, "set_inheritable") as inherit,
            patch.object(startup.os, "execv") as execute,
        ):
            r.launch(Path("/test/instance"), 42)
            inherit.assert_called_once_with(42, True)
            self.assertEqual(
                execute.call_args.args[1][1:],
                [
                    "dev",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "3000",
                    "--db-pool-max-overflow",
                    "80",
                    "--live-data-poll-rate",
                    "10000",
                ],
            )
            self.assertEqual(startup.os.environ["DAGSTER_HOME"], "/test/instance")

    def test_unhandled_error_does_not_print_secret(self):
        r = self.runtime()
        with (
            patch.object(startup, "Runtime", return_value=r),
            patch.object(startup, "configuration", side_effect=OSError("SECRET")),
        ):
            self.assertEqual(startup.main([]), 1)
        self.assertNotIn("SECRET", str(r.say.call_args_list))

    def test_main_launches_only_after_all_dependencies_ready(self):
        r = self.runtime()
        r.listening = Mock(return_value=False)
        r.ensure = Mock()
        r.launch = Mock()
        deps = (dependency(), dependency("CH", "ch"), dependency("Prod", "ch"))
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(startup, "Runtime", return_value=r),
            patch.object(startup, "configuration", return_value=(Path(temp), deps)),
        ):
            self.assertEqual(startup.main([]), 0)
        self.assertEqual(r.ensure.call_count, 3)
        r.launch.assert_called_once()

    def test_failure_never_launches_dg(self):
        r = self.runtime()
        r.listening = Mock(return_value=False)
        r.ensure = Mock(side_effect=startup.StartupError("依赖错误"))
        r.launch = Mock()
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(startup, "Runtime", return_value=r),
            patch.object(
                startup, "configuration", return_value=(Path(temp), (dependency(),))
            ),
        ):
            self.assertEqual(startup.main([]), 1)
        r.launch.assert_not_called()

    def test_lake_warning_preserves_launch_and_uses_feishu_contract(self):
        r = startup.Runtime(startup.StartupPolicy(), {})
        r.say = Mock()
        with patch.object(startup.Path, "is_mount", return_value=False):
            r.warnings()
        messages = str(r.say.call_args_list)
        self.assertIn("datasource", messages)
        self.assertIn("GOLDENSHARE_FEISHU_WEBHOOK_URL", messages)

    def test_command_timeout_terminates_only_spawned_group(self):
        r = startup.Runtime(startup.StartupPolicy(), {})
        child = Mock(pid=54321)
        child.communicate.side_effect = [
            subprocess.TimeoutExpired("helper", 40),
            (b"", b""),
        ]
        with (
            patch.object(startup.subprocess, "Popen", return_value=child),
            patch.object(startup.os, "killpg") as kill,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                r.command(["/fake/helper"])
            kill.assert_called_once_with(54321, startup.signal.SIGTERM)


class ConfigurationTests(unittest.TestCase):
    def environment(self):
        env = {}
        for prefix, port in (("CLICKHOUSE", "9000"), ("PROD_CLICKHOUSE", "19000")):
            env.update(
                {
                    f"{prefix}_HOST": "127.0.0.1",
                    f"{prefix}_PORT": port,
                    f"{prefix}_USER": "test",
                    f"{prefix}_PASSWORD": "",
                    f"{prefix}_DATABASE": "test",
                }
            )
        return env

    def config(self, home, url=None):
        path = home / ".goldenshare/dagster_home"
        path.mkdir(parents=True)
        (path / "dagster.yaml").write_text(
            json.dumps(
                {
                    "storage": {
                        "postgres": {
                            "postgres_url": url
                            or "postgresql://test@localhost:5432/goldenshare_dagster"
                        }
                    }
                }
            )
        )
        return path

    def test_existing_config_empty_password(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            expected = self.config(home)
            actual, deps = startup.configuration(self.environment(), home)
            self.assertEqual(actual, expected)
            self.assertEqual(len(deps), 3)

    def test_dsn_env_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.config(home, {"env": "PG_URL"})
            env = {
                **self.environment(),
                "PG_URL": "postgresql://test@localhost/goldenshare_dagster",
            }
            self.assertEqual(len(startup.configuration(env, home)[1]), 3)

    def test_other_instance_remote_pg_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with self.assertRaises(startup.StartupError):
                startup.configuration({"DAGSTER_HOME": "/not_formal"}, home)
            self.config(home, "postgresql://user:SECRET@remote/goldenshare_dagster")
            with self.assertRaises(startup.StartupError) as error:
                startup.configuration(self.environment(), home)
            self.assertNotIn("SECRET", str(error.exception))

    def test_missing_config_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with self.assertRaises(startup.StartupError):
                startup.configuration(self.environment(), home)
            self.assertEqual(list(home.iterdir()), [])

    def test_missing_env_different_local_ch_port_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self.config(home)
            for env in ({}, {**self.environment(), "CLICKHOUSE_PORT": "19000"}):
                with self.assertRaises(startup.StartupError):
                    startup.configuration(env, home)

    def test_manual_tunnel_default_unchanged_batch_noninteractive(self):
        helper = startup.BIN / "lake-prod-clickhouse-tunnel"
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "ssh"
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            fake.chmod(0o755)
            env = {"PATH": temp + ":/usr/bin:/bin"}
            for args, batch in (([], False), (["--batch"], True)):
                result = subprocess.run(
                    ["/bin/bash", str(helper), *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual("BatchMode=yes" in result.stdout, batch)
                self.assertIn("19000:127.0.0.1:9000", result.stdout)


if __name__ == "__main__":
    unittest.main()
