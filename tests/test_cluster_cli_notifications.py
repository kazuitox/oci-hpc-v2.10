import importlib.util
import ast
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from click.testing import CliRunner


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLUSTER_CLI_PATH = os.path.join(
    REPOSITORY_ROOT, "playbooks", "roles", "cluster-cli", "files", "cluster"
)


def load_cluster_cli():
    fake_ldap3 = types.ModuleType("ldap3")
    fake_ldap3.MODIFY_ADD = "MODIFY_ADD"
    fake_ldap3.Server = mock.Mock()
    fake_ldap3.Connection = mock.Mock()

    module_name = "cluster_cli_notifications_test"
    spec = importlib.util.spec_from_file_location(module_name, CLUSTER_CLI_PATH)
    if spec is None or spec.loader is None:
        # Extensionless scripts are not automatically assigned a source loader.
        from importlib.machinery import SourceFileLoader

        spec = importlib.util.spec_from_loader(
            module_name, SourceFileLoader(module_name, CLUSTER_CLI_PATH)
        )
    module = importlib.util.module_from_spec(spec)
    password_file = mock.mock_open(read_data="ldap-secret\n")
    with mock.patch.dict(sys.modules, {"ldap3": fake_ldap3}):
        with mock.patch("builtins.open", password_file):
            spec.loader.exec_module(module)
    return module


class ClusterCliNotificationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_cluster_cli()
        self.runner = CliRunner()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.registry_path = os.path.join(
            self.temporary_directory.name, "slurm_notification_users.json"
        )
        self.inventory_path = os.path.join(
            self.temporary_directory.name, "ansible-hosts"
        )
        self.module.notification_registry_path = self.registry_path
        self.module.ansible_inventory_path = self.inventory_path
        self.module.cluster_ssh_key_path = os.path.join(
            self.temporary_directory.name, "cluster.key"
        )
        self.write_inventory()

    def enabled_registry(self, users=None):
        return {
            "config": {
                "enabled": True,
                "region": "ap-tokyo-1",
                "compartment_id": "ocid1.compartment.test",
                "cluster_name": "trial-cluster",
                "cluster_scope_id": "scope-1234",
                "auth": "instance_principal",
            },
            "users": users or {},
        }

    def write_registry(self, registry):
        with open(self.registry_path, "w") as registry_file:
            json.dump(registry, registry_file)
        os.chmod(self.registry_path, 0o640)

    def read_registry(self):
        with open(self.registry_path, "r") as registry_file:
            return json.load(registry_file)

    def write_inventory(self, backup_entry=None):
        with open(self.inventory_path, "w") as inventory_file:
            inventory_file.write("[controller]\nprimary ansible_host=10.0.0.2\n")
            inventory_file.write("[slurm_backup]\n")
            if backup_entry:
                inventory_file.write(backup_entry + "\n")
            inventory_file.write("[compute_configured]\n")

    @staticmethod
    def successful_oci(command, **kwargs):
        if command[:4] == ["oci", "ons", "topic", "create"]:
            return SimpleNamespace(stdout="ocid1.onstopic.test\n", stderr="")
        if command[:4] == ["oci", "ons", "subscription", "create"]:
            return SimpleNamespace(stdout="ocid1.onssubscription.test\n", stderr="")
        return SimpleNamespace(stdout="", stderr="")

    def test_enabled_add_creates_ons_resources_stores_mail_and_routes_user(self):
        self.write_registry(self.enabled_registry())

        with mock.patch.object(
            self.module, "_create_ldap_user", return_value=False
        ) as create_ldap_user:
            with mock.patch.object(self.module, "_initialize_user_home"):
                with mock.patch.object(
                    self.module.subprocess,
                    "run",
                    side_effect=self.successful_oci,
                ) as run:
                    result = self.runner.invoke(
                        self.module.main,
                        [
                            "user",
                            "add",
                            "alice",
                            "--password",
                            "secret",
                            "--name",
                            "Alice Example",
                            "--uid",
                            "10101",
                            "--gid",
                            "9876",
                            "--email",
                            "alice@example.com",
                            "--nossh",
                        ],
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        create_ldap_user.assert_called_once_with(
            "alice",
            "secret",
            "10101",
            "9876",
            "Alice Example",
            email="alice@example.com",
        )
        registry = self.read_registry()
        self.assertEqual(
            registry["users"]["alice"],
            {
                "email": "alice@example.com",
                "topic_id": "ocid1.onstopic.test",
                "subscription_id": "ocid1.onssubscription.test",
                "managed_by": "cluster-cli",
            },
        )
        self.assertIn("must confirm", result.output)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][:4], ["oci", "ons", "topic", "create"])
        self.assertEqual(
            commands[1][:4], ["oci", "ons", "subscription", "create"]
        )
        self.assertIn("--auth", commands[0])
        self.assertEqual(
            commands[0][commands[0].index("--auth") + 1], "instance_principal"
        )
        self.assertEqual(
            commands[0][commands[0].index("--region") + 1], "ap-tokyo-1"
        )
        tags = json.loads(
            commands[0][commands[0].index("--freeform-tags") + 1]
        )
        self.assertEqual(tags["notification_scope"], "scope-1234")
        self.assertEqual(tags["slurm_user"], "alice")
        self.assertEqual(tags["managed_by"], "cluster-cli")

    def test_ldap_user_creation_stores_mail_attribute(self):
        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.result = {"result": 0}
        connection.add.return_value = True
        self.module.ldap3.Connection.return_value = connection

        with mock.patch.object(self.module, "exists", return_value=True):
            group_created = self.module._create_ldap_user(
                "alice",
                "secret",
                "10101",
                "9876",
                "Alice Example",
                email="alice@example.com",
            )

        self.assertFalse(group_created)
        attributes = connection.add.call_args.args[2]
        self.assertEqual(attributes["mail"], "alice@example.com")

    def test_enabled_delete_removes_route_before_ldap_then_deletes_ons(self):
        user_entry = {
            "email": "alice@example.com",
            "topic_id": "ocid1.onstopic.test",
            "subscription_id": "ocid1.onssubscription.test",
            "managed_by": "cluster-cli",
        }
        self.write_registry(self.enabled_registry({"alice": user_entry}))

        def delete_ldap_user(user):
            self.assertEqual(user, "alice")
            self.assertNotIn("alice", self.read_registry()["users"])

        with mock.patch.object(
            self.module, "_delete_ldap_user", side_effect=delete_ldap_user
        ) as delete_ldap_user_mock:
            with mock.patch.object(
                self.module.subprocess,
                "run",
                side_effect=self.successful_oci,
            ) as run:
                result = self.runner.invoke(
                    self.module.main, ["user", "delete", "alice"]
                )

        self.assertEqual(result.exit_code, 0, result.output)
        delete_ldap_user_mock.assert_called_once_with("alice")
        self.assertNotIn("alice", self.read_registry()["users"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands[0][:4], ["oci", "ons", "subscription", "delete"]
        )
        self.assertEqual(commands[1][:4], ["oci", "ons", "topic", "delete"])
        self.assertIn("--force", commands[0])
        self.assertIn("--force", commands[1])

    def test_absent_registry_preserves_legacy_add_without_email_or_ons(self):
        with mock.patch.object(
            self.module, "_create_ldap_user", return_value=False
        ) as create_ldap_user:
            with mock.patch.object(self.module, "_initialize_user_home"):
                with mock.patch.object(self.module.subprocess, "run") as run:
                    result = self.runner.invoke(
                        self.module.main,
                        [
                            "user",
                            "add",
                            "legacy",
                            "--password",
                            "secret",
                            "--name",
                            "Legacy User",
                            "--uid",
                            "10102",
                            "--gid",
                            "9876",
                            "--nossh",
                        ],
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        create_ldap_user.assert_called_once_with(
            "legacy",
            "secret",
            "10102",
            "9876",
            "Legacy User",
            email=None,
        )
        run.assert_not_called()
        self.assertFalse(os.path.exists(self.registry_path))

    def test_disabled_registry_preserves_legacy_add_without_email_or_ons(self):
        self.write_registry(
            {
                "config": {
                    "enabled": False,
                    "region": "",
                    "compartment_id": "",
                    "cluster_name": "",
                    "cluster_scope_id": "",
                    "auth": "instance_principal",
                },
                "users": {},
            }
        )
        with mock.patch.object(
            self.module, "_create_ldap_user", return_value=False
        ) as create_ldap_user:
            with mock.patch.object(self.module, "_initialize_user_home"):
                with mock.patch.object(self.module.subprocess, "run") as run:
                    result = self.runner.invoke(
                        self.module.main,
                        [
                            "user",
                            "add",
                            "legacy",
                            "--password",
                            "secret",
                            "--name",
                            "Legacy User",
                            "--uid",
                            "10102",
                            "--gid",
                            "9876",
                            "--nossh",
                        ],
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        create_ldap_user.assert_called_once()
        self.assertIsNone(create_ldap_user.call_args.kwargs["email"])
        run.assert_not_called()
        self.assertEqual(self.read_registry()["users"], {})

    def test_invalid_email_stops_before_ldap_and_oci(self):
        self.write_registry(self.enabled_registry())
        with mock.patch.object(self.module, "_create_ldap_user") as create_ldap_user:
            with mock.patch.object(self.module.subprocess, "run") as run:
                result = self.runner.invoke(
                    self.module.main,
                    [
                        "user",
                        "add",
                        "alice",
                        "--password",
                        "secret",
                        "--name",
                        "Alice Example",
                        "--uid",
                        "10101",
                        "--email",
                        "not-an-address",
                    ],
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("valid email address", result.output)
        create_ldap_user.assert_not_called()
        run.assert_not_called()
        self.assertEqual(self.read_registry()["users"], {})

    def test_ldap_failure_rolls_back_new_subscription_and_topic(self):
        self.write_registry(self.enabled_registry())
        with mock.patch.object(
            self.module,
            "_create_ldap_user",
            side_effect=self.module.NotificationError("duplicate LDAP user"),
        ):
            with mock.patch.object(self.module, "_initialize_user_home"):
                with mock.patch.object(
                    self.module.subprocess,
                    "run",
                    side_effect=self.successful_oci,
                ) as run:
                    result = self.runner.invoke(
                        self.module.main,
                        [
                            "user",
                            "add",
                            "alice",
                            "--password",
                            "secret",
                            "--name",
                            "Alice Example",
                            "--uid",
                            "10101",
                            "--email",
                            "alice@example.com",
                            "--nossh",
                        ],
                    )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("duplicate LDAP user", result.output)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            [command[:4] for command in commands],
            [
                ["oci", "ons", "topic", "create"],
                ["oci", "ons", "subscription", "create"],
                ["oci", "ons", "subscription", "delete"],
                ["oci", "ons", "topic", "delete"],
            ],
        )
        self.assertEqual(self.read_registry()["users"], {})

    def test_cluster_cli_refuses_to_delete_terraform_managed_opc(self):
        self.write_registry(
            self.enabled_registry(
                {
                    "opc": {
                        "email": "admin@example.com",
                        "topic_id": "ocid1.onstopic.opc",
                        "subscription_id": "ocid1.onssubscription.opc",
                        "managed_by": "terraform",
                    }
                }
            )
        )
        with mock.patch.object(self.module, "_delete_ldap_user") as delete_ldap_user:
            with mock.patch.object(self.module.subprocess, "run") as run:
                result = self.runner.invoke(
                    self.module.main, ["user", "delete", "opc"]
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cannot be deleted", result.output)
        delete_ldap_user.assert_not_called()
        run.assert_not_called()
        self.assertIn("opc", self.read_registry()["users"])

    def test_non_ha_backup_sync_is_a_noop(self):
        self.write_inventory()
        with mock.patch.object(self.module.subprocess, "run") as run:
            synchronized = self.module._sync_backup_registry(
                self.enabled_registry()
            )

        self.assertFalse(synchronized)
        run.assert_not_called()

    def test_ha_backup_sync_uses_inventory_and_sends_complete_snapshot(self):
        self.write_inventory(
            "backup-1 ansible_host=10.0.0.3 ansible_user=opc role=controller"
        )
        registry = self.enabled_registry(
            {
                "alice": {
                    "email": "alice@example.com",
                    "topic_id": "ocid1.onstopic.test",
                    "subscription_id": "ocid1.onssubscription.test",
                    "managed_by": "cluster-cli",
                }
            }
        )
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="", stderr=""),
        ) as run:
            synchronized = self.module._sync_backup_registry(registry)

        self.assertTrue(synchronized)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "ssh")
        self.assertIn("StrictHostKeyChecking=no", command)
        self.assertIn("opc@10.0.0.3", command)
        self.assertEqual(command[-3:-1], ["/usr/bin/python3", "-"])
        self.assertEqual(command[-1], self.registry_path)
        helper_input = run.call_args.kwargs["input"]
        encoded_payload = ast.literal_eval(
            helper_input.splitlines()[0].split("=", 1)[1].strip()
        )
        payload = self.module._decode_backup_snapshot(encoded_payload)
        self.assertEqual(payload["cluster_scope_id"], "scope-1234")
        self.assertEqual(payload["users"], registry["users"])
        self.assertTrue(helper_input.endswith(self.module.backup_sync_helper_source))
        self.assertNotIn("alice@example.com", " ".join(command))

    def test_ha_backup_sync_uses_latest_registry_instead_of_stale_caller_snapshot(self):
        self.write_inventory(
            "backup-1 ansible_host=10.0.0.3 ansible_user=opc role=controller"
        )
        stale_registry = self.enabled_registry(
            {
                "alice": {
                    "email": "alice@example.com",
                    "topic_id": "ocid1.onstopic.alice",
                    "subscription_id": "ocid1.onssubscription.alice",
                    "managed_by": "cluster-cli",
                }
            }
        )
        latest_registry = self.enabled_registry(
            dict(
                stale_registry["users"],
                bob={
                    "email": "bob@example.com",
                    "topic_id": "ocid1.onstopic.bob",
                    "subscription_id": "ocid1.onssubscription.bob",
                    "managed_by": "cluster-cli",
                },
            )
        )
        self.write_registry(latest_registry)

        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="", stderr=""),
        ) as run:
            synchronized = self.module._sync_backup_registry(stale_registry)

        self.assertTrue(synchronized)
        helper_input = run.call_args.kwargs["input"]
        encoded_payload = ast.literal_eval(
            helper_input.splitlines()[0].split("=", 1)[1].strip()
        )
        payload = self.module._decode_backup_snapshot(encoded_payload)
        self.assertEqual(payload["users"], latest_registry["users"])

    def test_routing_mutation_marks_backup_dirty_until_successful_sync(self):
        self.write_inventory(
            "backup-1 ansible_host=10.0.0.3 ansible_user=opc role=controller"
        )
        self.write_registry(self.enabled_registry())
        entry = {
            "email": "alice@example.com",
            "topic_id": "ocid1.onstopic.alice",
            "subscription_id": "ocid1.onssubscription.alice",
            "managed_by": "cluster-cli",
        }

        self.module._store_user_routing("alice", entry)
        self.assertIn(
            "pending_backup_sync", self.read_registry()["config"]
        )

        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="", stderr=""),
        ):
            synchronized = self.module._sync_backup_registry()

        self.assertTrue(synchronized)
        self.assertNotIn(
            "pending_backup_sync", self.read_registry()["config"]
        )

    def test_sync_does_not_clear_newer_dirty_marker_from_concurrent_mutation(self):
        self.write_inventory(
            "backup-1 ansible_host=10.0.0.3 ansible_user=opc role=controller"
        )
        self.write_registry(self.enabled_registry())
        alice = {
            "email": "alice@example.com",
            "topic_id": "ocid1.onstopic.alice",
            "subscription_id": "ocid1.onssubscription.alice",
            "managed_by": "cluster-cli",
        }
        bob = {
            "email": "bob@example.com",
            "topic_id": "ocid1.onstopic.bob",
            "subscription_id": "ocid1.onssubscription.bob",
            "managed_by": "cluster-cli",
        }
        self.module._store_user_routing("alice", alice)
        first_marker = dict(
            self.read_registry()["config"]["pending_backup_sync"]
        )

        def mutate_during_remote_sync(_backup, encoded_payload):
            payload = self.module._decode_backup_snapshot(encoded_payload)
            self.assertEqual(set(payload["users"]), {"alice"})
            self.module._store_user_routing("bob", bob)

        with mock.patch.object(
            self.module,
            "_run_backup_sync",
            side_effect=mutate_during_remote_sync,
        ):
            synchronized = self.module._sync_backup_registry()

        self.assertTrue(synchronized)
        registry = self.read_registry()
        self.assertEqual(set(registry["users"]), {"alice", "bob"})
        self.assertIn("pending_backup_sync", registry["config"])
        self.assertNotEqual(
            registry["config"]["pending_backup_sync"]["generation"],
            first_marker["generation"],
        )

    def test_remote_ha_helper_atomically_applies_snapshot(self):
        self.write_registry(
            self.enabled_registry(
                {
                    "opc": {
                        "email": "admin@example.com",
                        "topic_id": "ocid1.onstopic.opc",
                        "subscription_id": "ocid1.onssubscription.opc",
                        "managed_by": "terraform",
                    }
                }
            )
        )
        desired_registry = self.enabled_registry(
            {
                "alice": {
                    "email": "alice@example.com",
                    "topic_id": "ocid1.onstopic.alice",
                    "subscription_id": "ocid1.onssubscription.alice",
                    "managed_by": "cluster-cli",
                }
            }
        )
        encoded_payload = self.module._encode_backup_snapshot(desired_registry)
        helper_input = "encoded_payload = {!r}\n{}".format(
            encoded_payload, self.module.backup_sync_helper_source
        )

        result = subprocess.run(
            [sys.executable, "-", self.registry_path],
            input=helper_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        registry = self.read_registry()
        self.assertEqual(registry["users"], desired_registry["users"])
        self.assertEqual(registry["config"]["cluster_scope_id"], "scope-1234")

    def test_ha_add_sync_failure_keeps_local_ldap_and_oci_consistent(self):
        self.write_inventory(
            "backup-1 ansible_host=10.0.0.3 ansible_user=opc role=controller"
        )
        self.write_registry(self.enabled_registry())

        def oci_succeeds_but_ssh_fails(command, **kwargs):
            if command[0] == "ssh":
                raise self.module.subprocess.CalledProcessError(
                    255, command, stderr="backup unavailable"
                )
            return self.successful_oci(command, **kwargs)

        with mock.patch.object(
            self.module, "_create_ldap_user", return_value=False
        ) as create_ldap_user:
            with mock.patch.object(self.module, "_initialize_user_home"):
                with mock.patch.object(
                    self.module.subprocess,
                    "run",
                    side_effect=oci_succeeds_but_ssh_fails,
                ) as run:
                    result = self.runner.invoke(
                        self.module.main,
                        [
                            "user",
                            "add",
                            "alice",
                            "--password",
                            "secret",
                            "--name",
                            "Alice Example",
                            "--uid",
                            "10101",
                            "--email",
                            "alice@example.com",
                            "--nossh",
                        ],
                    )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("synchronization is pending", result.output)
        create_ldap_user.assert_called_once()
        registry = self.read_registry()
        self.assertIn("alice", registry["users"])
        self.assertIn("pending_backup_sync", registry["config"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            [command[:4] for command in commands if command[0] == "oci"],
            [
                ["oci", "ons", "topic", "create"],
                ["oci", "ons", "subscription", "create"],
            ],
        )

    def test_ha_delete_sync_failure_restores_route_before_stopping(self):
        self.write_inventory(
            "backup-1 ansible_host=10.0.0.3 ansible_user=opc role=controller"
        )
        user_entry = {
            "email": "alice@example.com",
            "topic_id": "ocid1.onstopic.test",
            "subscription_id": "ocid1.onssubscription.test",
            "managed_by": "cluster-cli",
        }
        self.write_registry(self.enabled_registry({"alice": user_entry}))

        def ssh_fails(command, **kwargs):
            self.assertEqual(command[0], "ssh")
            raise self.module.subprocess.CalledProcessError(
                255, command, stderr="backup unavailable"
            )

        with mock.patch.object(self.module, "_delete_ldap_user") as delete_ldap_user:
            with mock.patch.object(
                self.module.subprocess, "run", side_effect=ssh_fails
            ) as run:
                result = self.runner.invoke(
                    self.module.main, ["user", "delete", "alice"]
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("were not deleted", result.output)
        delete_ldap_user.assert_not_called()
        self.assertEqual(run.call_count, 2)
        registry = self.read_registry()
        self.assertEqual(registry["users"]["alice"], user_entry)
        self.assertIn("pending_backup_sync", registry["config"])

    def test_notification_cleanup_removes_successful_journal_entry_before_sync(self):
        registry = self.enabled_registry()
        registry["config"]["pending_cleanup"] = [
            {
                "username": "alice",
                "email": "alice@example.com",
                "topic_id": "ocid1.onstopic.test",
                "subscription_id": "ocid1.onssubscription.test",
                "managed_by": "cluster-cli",
                "errors": ["previous failure"],
                "recorded_at": "2026-09-04T00:00:00+00:00",
            }
        ]
        self.write_registry(registry)

        def assert_journal_was_committed(synchronized_registry):
            self.assertNotIn(
                "pending_cleanup", synchronized_registry["config"]
            )
            self.assertNotIn(
                "pending_cleanup", self.read_registry()["config"]
            )
            return False

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=self.successful_oci,
        ) as run:
            with mock.patch.object(
                self.module,
                "_sync_backup_registry",
                side_effect=assert_journal_was_committed,
            ) as synchronize:
                result = self.runner.invoke(
                    self.module.main, ["notification", "cleanup"]
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("removed 1 journal entries", result.output)
        synchronize.assert_called_once()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            [command[:4] for command in commands],
            [
                ["oci", "ons", "subscription", "delete"],
                ["oci", "ons", "topic", "delete"],
            ],
        )
        for command in commands:
            self.assertEqual(
                command[command.index("--auth") + 1], "instance_principal"
            )

    def test_notification_cleanup_keeps_only_failed_identifiers_and_latest_error(self):
        registry = self.enabled_registry()
        registry["config"]["pending_cleanup"] = [
            {
                "username": "alice",
                "email": "alice@example.com",
                "topic_id": "ocid1.onstopic.test",
                "subscription_id": "ocid1.onssubscription.test",
                "managed_by": "cluster-cli",
                "errors": ["stale error"],
                "recorded_at": "2026-09-04T00:00:00+00:00",
            }
        ]
        self.write_registry(registry)

        def subscription_succeeds_topic_fails(command, **kwargs):
            if command[:4] == ["oci", "ons", "topic", "delete"]:
                raise self.module.subprocess.CalledProcessError(
                    1, command, stderr="topic is temporarily unavailable"
                )
            return SimpleNamespace(stdout="", stderr="")

        def assert_partial_journal_was_committed(synchronized_registry):
            pending = synchronized_registry["config"]["pending_cleanup"]
            self.assertEqual(len(pending), 1)
            self.assertNotIn("subscription_id", pending[0])
            self.assertEqual(pending[0]["topic_id"], "ocid1.onstopic.test")
            return False

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=subscription_succeeds_topic_fails,
        ) as run:
            with mock.patch.object(
                self.module,
                "_sync_backup_registry",
                side_effect=assert_partial_journal_was_committed,
            ) as synchronize:
                result = self.runner.invoke(
                    self.module.main, ["notification", "cleanup"]
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cleanup still pending", result.output)
        synchronize.assert_called_once()
        pending = self.read_registry()["config"]["pending_cleanup"]
        self.assertEqual(len(pending), 1)
        self.assertNotIn("subscription_id", pending[0])
        self.assertEqual(pending[0]["topic_id"], "ocid1.onstopic.test")
        self.assertIn("topic is temporarily unavailable", pending[0]["errors"][0])
        self.assertNotIn("stale error", pending[0]["errors"])
        self.assertIn("cleanup_id", pending[0])
        self.assertIn("last_attempted_at", pending[0])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            [command[:4] for command in commands],
            [
                ["oci", "ons", "subscription", "delete"],
                ["oci", "ons", "topic", "delete"],
            ],
        )

    def test_notification_cleanup_records_backup_sync_failure_after_commit(self):
        registry = self.enabled_registry()
        registry["config"]["pending_cleanup"] = [
            {
                "username": "alice",
                "email": "alice@example.com",
                "topic_id": "ocid1.onstopic.test",
                "subscription_id": "ocid1.onssubscription.test",
                "managed_by": "cluster-cli",
                "errors": ["previous failure"],
                "recorded_at": "2026-09-04T00:00:00+00:00",
            }
        ]
        self.write_registry(registry)

        def fail_sync_after_commit(synchronized_registry):
            self.assertNotIn(
                "pending_cleanup", synchronized_registry["config"]
            )
            self.assertNotIn(
                "pending_cleanup", self.read_registry()["config"]
            )
            raise self.module.NotificationError("backup unavailable")

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=self.successful_oci,
        ):
            with mock.patch.object(
                self.module,
                "_sync_backup_registry",
                side_effect=fail_sync_after_commit,
            ):
                result = self.runner.invoke(
                    self.module.main, ["notification", "cleanup"]
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("backup synchronization is pending", result.output)
        config = self.read_registry()["config"]
        self.assertNotIn("pending_cleanup", config)
        self.assertIn("pending_backup_sync", config)
        self.assertIn("backup unavailable", config["pending_backup_sync"]["error"])

    def test_notification_cleanup_converges_after_prior_delete_completed(self):
        registry = self.enabled_registry()
        registry["config"]["pending_cleanup"] = [
            {
                "username": "alice",
                "email": "alice@example.com",
                "topic_id": "ocid1.onstopic.test",
                "managed_by": "cluster-cli",
                "errors": ["worker stopped after OCI accepted the delete"],
                "recorded_at": "2026-09-04T00:00:00+00:00",
            }
        ]
        self.write_registry(registry)

        def delete_was_already_completed(command, **kwargs):
            if command[:4] == ["oci", "ons", "topic", "delete"]:
                raise self.module.subprocess.CalledProcessError(
                    1,
                    command,
                    stderr="ServiceError: NotAuthorizedOrNotFound, status: 404",
                )
            if command[:4] == ["oci", "ons", "topic", "list"]:
                return SimpleNamespace(stdout=json.dumps({"data": []}), stderr="")
            return SimpleNamespace(stdout="", stderr="")

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=delete_was_already_completed,
        ) as run:
            result = self.runner.invoke(
                self.module.main, ["notification", "cleanup"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn(
            "pending_cleanup", self.read_registry()["config"]
        )
        self.assertEqual(
            [call.args[0][:4] for call in run.call_args_list],
            [
                ["oci", "ons", "topic", "delete"],
                ["oci", "ons", "topic", "list"],
            ],
        )

    def test_notification_cleanup_keeps_404_when_absence_cannot_be_authorized(self):
        registry = self.enabled_registry()
        registry["config"]["pending_cleanup"] = [
            {
                "username": "alice",
                "email": "alice@example.com",
                "topic_id": "ocid1.onstopic.test",
                "managed_by": "cluster-cli",
                "errors": ["previous failure"],
                "recorded_at": "2026-09-04T00:00:00+00:00",
            }
        ]
        self.write_registry(registry)

        def authorization_is_unavailable(command, **kwargs):
            raise self.module.subprocess.CalledProcessError(
                1,
                command,
                stderr="ServiceError: NotAuthorizedOrNotFound, status: 404",
            )

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=authorization_is_unavailable,
        ):
            result = self.runner.invoke(
                self.module.main, ["notification", "cleanup"]
            )

        self.assertNotEqual(result.exit_code, 0)
        pending = self.read_registry()["config"]["pending_cleanup"]
        self.assertEqual(pending[0]["topic_id"], "ocid1.onstopic.test")
        self.assertIn("absence verification failed", pending[0]["errors"][0])


if __name__ == "__main__":
    unittest.main()
