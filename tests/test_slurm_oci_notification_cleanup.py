import ast
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "slurm",
    "files",
    "slurm_oci_notification_cleanup.py",
)
CLUSTER_CLI_PATH = os.path.join(
    REPOSITORY_ROOT, "playbooks", "roles", "cluster-cli", "files", "cluster"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "slurm_oci_notification_cleanup_test", HELPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SlurmOciNotificationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.config = {
            "region": "ap-osaka-1",
            "compartment_id": "ocid1.compartment.oc1..example",
            "cluster_name": "slurm-mail",
            "cluster_scope_id": "slurm-mail:firm-earwig:7c586774a476",
            "deployment_id": "0123456789abcdef0123456789abcdef",
            "registry_path": os.path.join(
                self.temp_directory.name, "slurm_notification_users.json"
            ),
            "protected_topic_ids": set(),
        }

    @staticmethod
    def result(data=None, stdout=None, returncode=0, stderr=""):
        if stdout is None:
            stdout = json.dumps({"data": [] if data is None else data})
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def topic(self, username, topic_id=None, **overrides):
        topic_id = topic_id or "ocid1.onstopic.oc1.ap-osaka-1.{}".format(username)
        value = {
            "topic-id": topic_id,
            "name": self.module.notification_topic_name(self.config, username),
            "lifecycle-state": "ACTIVE",
            "freeform-tags": {
                "managed_by": "cluster-cli",
                "notification_scope": self.config["cluster_scope_id"],
                "notification_deployment_id": self.config["deployment_id"],
                "cluster_name": self.config["cluster_name"],
                "parent_cluster": self.config["cluster_name"],
                "slurm_user": username,
            },
        }
        value.update(overrides)
        return value

    def test_topic_name_matches_cluster_cli_deterministic_suffix(self):
        self.assertEqual(
            self.module.notification_topic_name(self.config, "notifytest"),
            "slurm-slurm-mail-notifytest-5013a2c964da",
        )

    def test_topic_name_implementation_matches_cluster_cli(self):
        with open(CLUSTER_CLI_PATH, encoding="utf-8") as source:
            tree = ast.parse(source.read(), filename=CLUSTER_CLI_PATH)
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in ("_topic_component", "_notification_topic_name")
        ]
        self.assertEqual(len(functions), 2)
        module = ast.Module(body=functions)
        if "type_ignores" in getattr(module, "_fields", ()):
            module.type_ignores = []
        namespace = {"hashlib": hashlib, "re": re}
        exec(compile(module, CLUSTER_CLI_PATH, "exec"), namespace)

        for username in ("notifytest", "UPPER.case", "x" * 80):
            with self.subTest(username=username):
                self.assertEqual(
                    self.module.notification_topic_name(self.config, username),
                    namespace["_notification_topic_name"](self.config, username),
                )

    def test_decodes_and_validates_base64_json_configuration(self):
        payload = dict(self.config, protected_topic_ids=["ocid1.onstopic.oc1.safe"])
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        decoded = self.module.decode_config(encoded)
        self.assertEqual(decoded["region"], "ap-osaka-1")
        self.assertEqual(
            decoded["protected_topic_ids"], {"ocid1.onstopic.oc1.safe"}
        )

    def test_loads_current_scope_when_registry_does_not_exist(self):
        self.assertEqual(
            self.module.load_cleanup_scopes(self.config),
            [
                {
                    "cluster_name": self.config["cluster_name"],
                    "cluster_scope_id": self.config["cluster_scope_id"],
                }
            ],
        )

    def test_deletes_topic_from_historical_scope_recorded_in_registry(self):
        historical = {
            "cluster_name": "old-slurm-mail",
            "cluster_scope_id": "old-slurm-mail:firm-earwig:7c586774a476",
        }
        with open(self.config["registry_path"], "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "config": {
                        "cluster_name": self.config["cluster_name"],
                        "cluster_scope_id": self.config["cluster_scope_id"],
                        "deployment_id": self.config["deployment_id"],
                        "cleanup_scopes": [historical, historical],
                    },
                    "users": {},
                },
                stream,
            )
        old_topic = self.topic("alice")
        old_topic["freeform-tags"].pop("notification_deployment_id")
        old_topic["name"] = self.module.notification_topic_name(
            historical, "alice"
        )
        old_topic["freeform-tags"].update(
            {
                "notification_scope": historical["cluster_scope_id"],
                "cluster_name": historical["cluster_name"],
                "parent_cluster": historical["cluster_name"],
            }
        )
        responses = [
            self.result([old_topic]),
            self.result(stdout=""),
            self.result([]),
        ]
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            deleted = self.module.cleanup_topics(
                self.config, executable="/test/oci", sleeper=lambda delay: None
            )
        self.assertEqual(deleted, 1)
        self.assertIn(old_topic["topic-id"], run.call_args_list[1].args[0])

    def test_deployment_tag_finds_old_scope_without_registry_history(self):
        historical = {
            "cluster_name": "old-slurm-mail",
            "cluster_scope_id": "old-slurm-mail:firm-earwig:7c586774a476",
        }
        old_topic = self.topic("alice")
        old_topic["name"] = self.module.notification_topic_name(
            historical, "alice"
        )
        old_topic["freeform-tags"].update(
            {
                "notification_scope": historical["cluster_scope_id"],
                "cluster_name": historical["cluster_name"],
                "parent_cluster": historical["cluster_name"],
            }
        )
        responses = [
            self.result([old_topic]),
            self.result(stdout=""),
            self.result([]),
        ]
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            deleted = self.module.cleanup_topics(
                self.config, executable="/test/oci", sleeper=lambda delay: None
            )
        self.assertEqual(deleted, 1)
        self.assertIn(old_topic["topic-id"], run.call_args_list[1].args[0])

    def test_different_deployment_tag_is_never_deleted(self):
        foreign = self.topic("alice")
        foreign["freeform-tags"]["notification_deployment_id"] = "f" * 32
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([foreign]),
        ) as run:
            deleted = self.module.cleanup_topics(
                self.config, executable="/test/oci"
            )
        self.assertEqual(deleted, 0)
        self.assertEqual(run.call_count, 2)
        self.assertFalse(
            any("delete" in call.args[0] for call in run.call_args_list)
        )

    def test_matching_deployment_tag_requires_compatible_self_described_scope(self):
        incompatible_scope = {
            "cluster_name": "old-slurm-mail",
            "cluster_scope_id": "old-slurm-mail:another-pet:7c586774a476",
        }
        topic = self.topic("alice")
        topic["name"] = self.module.notification_topic_name(
            incompatible_scope, "alice"
        )
        topic["freeform-tags"].update(
            {
                "notification_scope": incompatible_scope["cluster_scope_id"],
                "cluster_name": incompatible_scope["cluster_name"],
                "parent_cluster": incompatible_scope["cluster_name"],
            }
        )
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([topic]),
        ) as run:
            with self.assertRaisesRegex(
                self.module.CleanupError, "incompatible notification scope"
            ):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_matching_deployment_tag_requires_consistent_cluster_tags(self):
        topic = self.topic("alice")
        topic["freeform-tags"]["parent_cluster"] = "another-cluster"
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([topic]),
        ) as run:
            with self.assertRaisesRegex(
                self.module.CleanupError, "invalid cluster tags"
            ):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_matching_deployment_tag_requires_cluster_cli_ownership(self):
        topic = self.topic("alice")
        topic["freeform-tags"]["managed_by"] = "manual"
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([topic]),
        ) as run:
            with self.assertRaisesRegex(
                self.module.CleanupError, "invalid ownership tags"
            ):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_scope_history_must_belong_to_the_current_deployment(self):
        invalid_histories = (
            {
                "cluster_name": "old-name",
                "cluster_scope_id": "wrong-prefix:firm-earwig:7c586774a476",
            },
            {
                "cluster_name": "old-name",
                "cluster_scope_id": "old-name:another-pet:7c586774a476",
            },
            {
                "cluster_name": "old-name",
                "cluster_scope_id": "old-name:firm-earwig:000000000000",
            },
        )
        for historical in invalid_histories:
            with self.subTest(historical=historical):
                registry = {
                    "config": {
                        "cluster_name": self.config["cluster_name"],
                        "cluster_scope_id": self.config["cluster_scope_id"],
                        "deployment_id": self.config["deployment_id"],
                        "cleanup_scopes": [historical],
                    },
                    "users": {},
                }
                with open(
                    self.config["registry_path"], "w", encoding="utf-8"
                ) as stream:
                    json.dump(registry, stream)
                with mock.patch.object(self.module.subprocess, "run") as run:
                    with self.assertRaises(self.module.CleanupError):
                        self.module.cleanup_topics(
                            self.config, executable="/test/oci"
                        )
                run.assert_not_called()

    def test_scope_validation_accepts_cluster_names_truncated_to_128_characters(self):
        long_name = "a" * 140
        historical = {
            "cluster_name": long_name,
            "cluster_scope_id": "{}:firm-earwig:7c586774a476".format(
                long_name[:128]
            ),
        }
        registry = {
            "config": {
                "cluster_name": self.config["cluster_name"],
                "cluster_scope_id": self.config["cluster_scope_id"],
                "deployment_id": self.config["deployment_id"],
                "cleanup_scopes": [historical],
            },
            "users": {},
        }
        with open(self.config["registry_path"], "w", encoding="utf-8") as stream:
            json.dump(registry, stream)
        self.assertEqual(
            self.module.load_cleanup_scopes(self.config)[1], historical
        )

    def test_malformed_registry_history_fails_before_oci_access(self):
        valid_registry_config = {
            "cluster_name": self.config["cluster_name"],
            "cluster_scope_id": self.config["cluster_scope_id"],
            "deployment_id": self.config["deployment_id"],
        }
        malformed_values = (
            "not-json",
            json.dumps([]),
            json.dumps(
                {"config": dict(valid_registry_config, cleanup_scopes={})}
            ),
            json.dumps(
                {"config": dict(valid_registry_config, cleanup_scopes=[{}])}
            ),
        )
        for value in malformed_values:
            with self.subTest(value=value):
                with open(
                    self.config["registry_path"], "w", encoding="utf-8"
                ) as stream:
                    stream.write(value)
                with mock.patch.object(self.module.subprocess, "run") as run:
                    with self.assertRaises(self.module.CleanupError):
                        self.module.cleanup_topics(
                            self.config, executable="/test/oci"
                        )
                run.assert_not_called()

    def test_registry_deployment_id_mismatch_fails_before_oci_access(self):
        registry = {
            "config": {
                "cluster_name": self.config["cluster_name"],
                "cluster_scope_id": self.config["cluster_scope_id"],
                "deployment_id": "f" * 32,
            },
            "users": {},
        }
        with open(self.config["registry_path"], "w", encoding="utf-8") as stream:
            json.dump(registry, stream)
        with mock.patch.object(self.module.subprocess, "run") as run:
            with self.assertRaisesRegex(
                self.module.CleanupError, "another deployment"
            ):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_not_called()

    def test_registered_cluster_cli_topic_must_pass_strict_ownership_validation(self):
        topic_id = "ocid1.onstopic.oc1.ap-osaka-1.registered"
        registry = {
            "config": {
                "cluster_name": self.config["cluster_name"],
                "cluster_scope_id": self.config["cluster_scope_id"],
                "deployment_id": self.config["deployment_id"],
            },
            "users": {
                "alice": {
                    "managed_by": "cluster-cli",
                    "topic_id": topic_id,
                },
                "opc": {
                    "managed_by": "terraform",
                    "topic_id": "not-validated-for-terraform-entry",
                },
            },
        }
        with open(self.config["registry_path"], "w", encoding="utf-8") as stream:
            json.dump(registry, stream)
        drifted = self.topic("alice", topic_id=topic_id)
        drifted["freeform-tags"]["notification_deployment_id"] = "f" * 32
        otherwise_owned = self.topic("bob")

        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([otherwise_owned, drifted]),
        ) as run:
            with self.assertRaisesRegex(
                self.module.CleanupError, "failed ownership validation"
            ):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_pending_cluster_cli_topic_is_also_checked_for_drift(self):
        topic_id = "ocid1.onstopic.oc1.ap-osaka-1.pending"
        registry = {
            "config": {
                "cluster_name": self.config["cluster_name"],
                "cluster_scope_id": self.config["cluster_scope_id"],
                "deployment_id": self.config["deployment_id"],
                "pending_cleanup": [
                    {
                        "managed_by": "cluster-cli",
                        "topic_id": topic_id,
                    }
                ],
            },
            "users": {},
        }
        with open(self.config["registry_path"], "w", encoding="utf-8") as stream:
            json.dump(registry, stream)
        drifted = self.topic("alice", topic_id=topic_id, name="wrong-name")
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([drifted]),
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "deterministic name"):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_invalid_cluster_cli_registry_topic_ocid_fails_before_oci_access(self):
        base_config = {
            "cluster_name": self.config["cluster_name"],
            "cluster_scope_id": self.config["cluster_scope_id"],
            "deployment_id": self.config["deployment_id"],
        }
        registries = (
            {
                "config": base_config,
                "users": {
                    "alice": {
                        "managed_by": "cluster-cli",
                        "topic_id": "not-a-topic-ocid",
                    }
                },
            },
            {
                "config": dict(
                    base_config,
                    pending_cleanup=[
                        {
                            "managed_by": "cluster-cli",
                            "topic_id": "ocid1.onstopic.",
                        }
                    ],
                ),
                "users": {},
            },
        )
        for registry in registries:
            with self.subTest(registry=registry):
                with open(
                    self.config["registry_path"], "w", encoding="utf-8"
                ) as stream:
                    json.dump(registry, stream)
                with mock.patch.object(self.module.subprocess, "run") as run:
                    with self.assertRaisesRegex(self.module.CleanupError, "Topic OCID"):
                        self.module.cleanup_topics(
                            self.config, executable="/test/oci"
                        )
                run.assert_not_called()

    def test_registry_structure_errors_fail_before_oci_access(self):
        base_config = {
            "cluster_name": self.config["cluster_name"],
            "cluster_scope_id": self.config["cluster_scope_id"],
            "deployment_id": self.config["deployment_id"],
        }
        registries = (
            {"config": base_config, "users": []},
            {"config": base_config, "users": {"alice": []}},
            {
                "config": dict(base_config, pending_cleanup={}),
                "users": {},
            },
            {
                "config": dict(base_config, pending_cleanup=[[]]),
                "users": {},
            },
        )
        for registry in registries:
            with self.subTest(registry=registry):
                with open(
                    self.config["registry_path"], "w", encoding="utf-8"
                ) as stream:
                    json.dump(registry, stream)
                with mock.patch.object(self.module.subprocess, "run") as run:
                    with self.assertRaises(self.module.CleanupError):
                        self.module.cleanup_topics(
                            self.config, executable="/test/oci"
                        )
                run.assert_not_called()

    def test_protected_and_terraform_registry_topics_are_excluded(self):
        protected = self.topic("opc")
        topic_id = protected["topic-id"]
        self.config["protected_topic_ids"] = {topic_id}
        registry = {
            "config": {
                "cluster_name": self.config["cluster_name"],
                "cluster_scope_id": self.config["cluster_scope_id"],
                "deployment_id": self.config["deployment_id"],
            },
            "users": {
                "protected": {
                    "managed_by": "cluster-cli",
                    "topic_id": topic_id,
                },
                "opc": {
                    "managed_by": "terraform",
                    "topic_id": "not-a-topic-ocid",
                },
            },
        }
        with open(self.config["registry_path"], "w", encoding="utf-8") as stream:
            json.dump(registry, stream)
        protected["name"] = None
        protected["freeform-tags"] = "unexpected"
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([protected]),
        ) as run:
            deleted = self.module.cleanup_topics(
                self.config, executable="/test/oci"
            )
        self.assertEqual(deleted, 0)
        self.assertEqual(run.call_count, 2)

    def test_rejects_invalid_base64_and_invalid_protected_id(self):
        with self.assertRaisesRegex(self.module.CleanupError, "base64 JSON"):
            self.module.decode_config("not base64!")

        payload = dict(self.config, protected_topic_ids=["not-a-topic"])
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        with self.assertRaisesRegex(self.module.CleanupError, "protected Topic OCID"):
            self.module.decode_config(encoded)

        payload = dict(
            self.config,
            deployment_id="NOT-A-DEPLOYMENT-ID",
            protected_topic_ids=[],
        )
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        with self.assertRaisesRegex(self.module.CleanupError, "deployment_id"):
            self.module.decode_config(encoded)

    def test_deletes_only_owned_exactly_named_unprotected_topics_and_polls(self):
        owned = self.topic("alice")
        # Legacy orphan: cleanup deliberately does not require either tag.
        self.assertNotIn("notification_provision_id", owned["freeform-tags"])
        owned["freeform-tags"].pop("notification_deployment_id")
        protected = self.topic("opc")
        foreign = self.topic("mallory")
        foreign["freeform-tags"].pop("notification_deployment_id")
        foreign["freeform-tags"]["notification_scope"] = "another-scope"
        self.config["protected_topic_ids"] = {protected["topic-id"]}

        responses = [
            self.result([owned, protected, foreign]),
            self.result(stdout=""),  # successful delete
            self.result([owned, protected, foreign]),
            self.result([protected, foreign]),
        ]
        sleeps = []
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            deleted = self.module.cleanup_topics(
                self.config,
                executable="/test/oci",
                sleeper=sleeps.append,
                poll_attempts=3,
                poll_interval=0.25,
            )

        self.assertEqual(deleted, 1)
        self.assertEqual(sleeps, [0.25])
        commands = [call.args[0] for call in run.call_args_list]
        delete_commands = [command for command in commands if "delete" in command]
        self.assertEqual(len(delete_commands), 1)
        self.assertIn(owned["topic-id"], delete_commands[0])
        self.assertNotIn(protected["topic-id"], delete_commands[0])
        self.assertNotIn("subscription", delete_commands[0])
        list_command = commands[0]
        self.assertIn("--all", list_command)
        self.assertEqual(list_command[list_command.index("--output") + 1], "json")
        self.assertEqual(list_command[list_command.index("--query") + 1], "@")
        self.assertEqual(
            list_command[list_command.index("--auth") + 1], "instance_principal"
        )

    def test_empty_stdout_fails_closed(self):
        with mock.patch.object(
            self.module.subprocess, "run", return_value=self.result(stdout=" \n")
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "empty Topic list"):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_explicit_empty_json_list_is_idempotent(self):
        with mock.patch.object(
            self.module.subprocess, "run", return_value=self.result([])
        ) as run:
            deleted = self.module.cleanup_topics(self.config, executable="/test/oci")
        self.assertEqual(deleted, 0)
        self.assertEqual(run.call_count, 2)

    def test_owned_topic_appearing_after_initial_empty_list_is_deleted(self):
        concurrent = self.topic("alice")
        responses = [
            self.result([]),
            self.result([concurrent]),
            self.result(stdout=""),
            self.result([]),
        ]
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            cleaned = self.module.cleanup_topics(
                self.config,
                executable="/test/oci",
                sleeper=lambda delay: None,
                poll_attempts=2,
            )
        self.assertEqual(cleaned, 1)
        delete_commands = [
            call.args[0] for call in run.call_args_list if "delete" in call.args[0]
        ]
        self.assertEqual(len(delete_commands), 1)
        self.assertIn(concurrent["topic-id"], delete_commands[0])

    def test_protected_owned_topic_is_never_deleted(self):
        protected = self.topic("opc")
        self.config["protected_topic_ids"] = {protected["topic-id"]}
        # OCID protection takes precedence over mutable metadata validation.
        protected["name"] = None
        protected["freeform-tags"] = "unexpected"
        protected["lifecycle-state"] = "UNKNOWN_ENUM_VALUE"
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([protected]),
        ) as run:
            deleted = self.module.cleanup_topics(self.config, executable="/test/oci")
        self.assertEqual(deleted, 0)
        self.assertEqual(run.call_count, 2)

    def test_owned_topic_requires_a_known_lifecycle_state_before_delete(self):
        for lifecycle_override in (
            {},
            {"lifecycle-state": "UNKNOWN_ENUM_VALUE"},
            {"lifecycle-state": "DELETED"},
        ):
            invalid = self.topic("alice")
            if lifecycle_override:
                invalid.update(lifecycle_override)
            else:
                invalid.pop("lifecycle-state")
            with self.subTest(topic=invalid), mock.patch.object(
                self.module.subprocess,
                "run",
                return_value=self.result([invalid]),
            ) as run:
                with self.assertRaisesRegex(
                    self.module.CleanupError, "lifecycle state"
                ):
                    self.module.cleanup_topics(self.config, executable="/test/oci")
                run.assert_called_once()

    def test_creating_topic_is_deleted_and_deleting_topic_is_only_polled(self):
        creating = self.topic("alice", **{"lifecycle-state": "CREATING"})
        deleting = self.topic("bob", **{"lifecycle-state": "DELETING"})
        responses = [
            self.result([creating, deleting]),
            self.result(stdout=""),
            self.result([]),
        ]
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            cleaned = self.module.cleanup_topics(
                self.config, executable="/test/oci", sleeper=lambda delay: None
            )
        self.assertEqual(cleaned, 2)
        delete_commands = [
            call.args[0] for call in run.call_args_list if "delete" in call.args[0]
        ]
        self.assertEqual(len(delete_commands), 1)
        self.assertIn(creating["topic-id"], delete_commands[0])
        self.assertNotIn(deleting["topic-id"], delete_commands[0])

    def test_new_owned_topic_seen_while_polling_is_deleted_and_confirmed_absent(self):
        initial = self.topic("alice")
        concurrent = self.topic("bob")
        responses = [
            self.result([initial]),
            self.result(stdout=""),
            self.result([initial, concurrent]),
            self.result(stdout=""),
            self.result([]),
        ]
        sleeps = []
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            cleaned = self.module.cleanup_topics(
                self.config,
                executable="/test/oci",
                sleeper=sleeps.append,
                poll_attempts=3,
                poll_interval=0.25,
            )
        self.assertEqual(cleaned, 2)
        self.assertEqual(sleeps, [0.25])
        delete_commands = [
            call.args[0] for call in run.call_args_list if "delete" in call.args[0]
        ]
        self.assertEqual(len(delete_commands), 2)
        self.assertIn(initial["topic-id"], delete_commands[0])
        self.assertIn(concurrent["topic-id"], delete_commands[1])

    def test_owned_topic_delete_is_not_repeated_during_polling(self):
        owned = self.topic("alice")
        responses = [
            self.result([owned]),
            self.result(stdout=""),
            self.result([owned]),
            self.result([owned]),
            self.result([]),
        ]
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            cleaned = self.module.cleanup_topics(
                self.config,
                executable="/test/oci",
                sleeper=lambda delay: None,
                poll_attempts=3,
            )
        self.assertEqual(cleaned, 1)
        delete_commands = [
            call.args[0] for call in run.call_args_list if "delete" in call.args[0]
        ]
        self.assertEqual(len(delete_commands), 1)

    def test_default_poll_window_is_about_one_minute(self):
        self.assertEqual(self.module.POLL_ATTEMPTS, 30)
        self.assertEqual(self.module.POLL_INTERVAL_SECONDS, 2)

    def test_owned_topic_with_wrong_name_fails_before_any_delete(self):
        valid = self.topic("alice")
        invalid = self.topic("bob", name="slurm-wrong-name")
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([valid, invalid]),
        ) as run:
            with self.assertRaisesRegex(
                self.module.CleanupError, "deterministic name"
            ):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_owned_topic_without_nonempty_user_tag_fails_closed(self):
        invalid = self.topic("alice")
        invalid["freeform-tags"]["slurm_user"] = ""
        with mock.patch.object(
            self.module.subprocess,
            "run",
            return_value=self.result([invalid]),
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "slurm_user"):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        run.assert_called_once()

    def test_malformed_list_output_and_topic_ocid_fail_closed(self):
        for response in (
            self.result(stdout="not-json"),
            self.result(stdout=json.dumps({"data": {}})),
            self.result([{"topic-id": "not-an-ocid", "name": "topic"}]),
        ):
            with self.subTest(stdout=response.stdout), mock.patch.object(
                self.module.subprocess, "run", return_value=response
            ) as run:
                with self.assertRaisesRegex(self.module.CleanupError, "malformed"):
                    self.module.cleanup_topics(self.config, executable="/test/oci")
                run.assert_called_once()

    def test_oci_list_failure_and_timeout_fail_closed(self):
        failure = self.result(returncode=1, stderr="service unavailable")
        with mock.patch.object(
            self.module.subprocess, "run", return_value=failure
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "service unavailable"):
                self.module.cleanup_topics(self.config, executable="/test/oci")
            run.assert_called_once()

        timeout = subprocess.TimeoutExpired(["oci"], 120)
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=timeout
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "timed out"):
                self.module.cleanup_topics(self.config, executable="/test/oci")
            run.assert_called_once()

    def test_delete_failure_is_reported_without_polling(self):
        owned = self.topic("alice")
        responses = [
            self.result([owned]),
            self.result(returncode=1, stderr="delete denied"),
        ]
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "delete denied"):
                self.module.cleanup_topics(self.config, executable="/test/oci")
        self.assertEqual(run.call_count, 2)

    def test_finite_poll_timeout_reports_remaining_topic(self):
        owned = self.topic("alice")
        responses = [
            self.result([owned]),
            self.result(stdout=""),
            self.result([owned]),
            self.result([owned]),
        ]
        sleeps = []
        with mock.patch.object(
            self.module.subprocess, "run", side_effect=responses
        ) as run:
            with self.assertRaisesRegex(self.module.CleanupError, "timed out waiting"):
                self.module.cleanup_topics(
                    self.config,
                    executable="/test/oci",
                    sleeper=sleeps.append,
                    poll_attempts=2,
                    poll_interval=0.5,
                )
        self.assertEqual(run.call_count, 4)
        self.assertEqual(sleeps, [0.5])

    def test_finds_oci_in_current_users_local_bin_without_path_lookup(self):
        local_oci = os.path.join("/home/opc", ".local", "bin", "oci")
        with mock.patch.object(self.module.os.path, "expanduser", return_value="/home/opc"), mock.patch.object(
            self.module.os.path, "isfile", side_effect=lambda path: path == local_oci
        ), mock.patch.object(
            self.module.os, "access", return_value=True
        ), mock.patch.object(
            self.module.shutil, "which"
        ) as which:
            self.assertEqual(self.module.find_oci(), local_oci)
        which.assert_not_called()


if __name__ == "__main__":
    unittest.main()
