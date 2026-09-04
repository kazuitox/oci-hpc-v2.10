import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLURM_FILES = os.path.join(REPOSITORY_ROOT, "playbooks", "roles", "slurm", "files")


def load_module(name, filename):
    path = os.path.join(SLURM_FILES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SlurmOciMailProgTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("slurm_oci_mailprog_test", "slurm_oci_mailprog.py")
        self.registry = {
            "config": {"enabled": True, "region": "ap-tokyo-1"},
            "users": {
                "alice": {
                    "topic_id": "ocid1.onstopic.oc1.ap-tokyo-1.example",
                    "managed_by": "cluster-cli",
                }
            },
        }

    def test_queues_slurm_subject_body_and_event_for_registered_owner(self):
        environment = {
            "SLURM_JOB_USER": "alice",
            "SLURM_JOB_ID": "42",
            "SLURM_JOB_MAIL_TYPE": "BEGIN",
        }
        with tempfile.TemporaryDirectory() as spool:
            with mock.patch.object(self.module, "read_body", return_value="job body"):
                queued = self.module.queue_message(
                    self.registry,
                    ["-s", "Slurm Job_id=42 Began", "ignored@example.com"],
                    environment,
                    spool_path=spool,
                )
            self.assertTrue(queued)
            messages = [name for name in os.listdir(spool) if name.endswith(".json")]
            self.assertEqual(len(messages), 1)
            with open(os.path.join(spool, messages[0]), encoding="utf-8") as stream:
                message = json.load(stream)
            self.assertEqual(message["username"], "alice")
            self.assertEqual(message["job_id"], "42")
            self.assertEqual(message["mail_type"], "BEGIN")
            self.assertEqual(message["title"], "Slurm Job_id=42 Began")
            self.assertEqual(message["body"], "job body")
            self.assertEqual(message["region"], "ap-tokyo-1")

    def test_normalizes_slurm_23_mail_event_and_builds_nonempty_body(self):
        self.registry["config"]["cluster_name"] = "trial"
        environment = {
            "SLURM_JOB_USER": "alice",
            "SLURM_JOB_ID": "43",
            "SLURM_JOB_NAME": "solver",
            "SLURM_JOB_MAIL_TYPE": "Failed",
            "SLURM_JOB_STATE": "FAILED",
            "SLURM_JOB_EXIT_CODE_MAX": "2",
        }
        with tempfile.TemporaryDirectory() as spool:
            with mock.patch.object(self.module, "read_body", return_value=""):
                queued = self.module.queue_message(
                    self.registry,
                    ["-s", "Slurm Job_id=43 Name=solver Failed"],
                    environment,
                    spool_path=spool,
                )
            self.assertTrue(queued)
            message_path = next(
                os.path.join(spool, name)
                for name in os.listdir(spool)
                if name.endswith(".json")
            )
            with open(message_path, encoding="utf-8") as stream:
                message = json.load(stream)
        self.assertEqual(message["mail_type"], "FAIL")
        self.assertIn("Cluster: trial", message["body"])
        self.assertIn("Job name: solver", message["body"])
        self.assertIn("Exit code: 2", message["body"])

    def test_limits_escaped_body_to_oci_publish_payload_budget(self):
        environment = {
            "SLURM_JOB_USER": "alice",
            "SLURM_JOB_ID": "44",
            "SLURM_JOB_MAIL_TYPE": "Ended",
        }
        with tempfile.TemporaryDirectory() as spool:
            with mock.patch.object(
                self.module, "read_body", return_value="\x00" * (60 * 1024)
            ):
                self.module.queue_message(
                    self.registry,
                    ["-s", "Slurm Job_id=44 Ended"],
                    environment,
                    spool_path=spool,
                )
            message_path = next(
                os.path.join(spool, name)
                for name in os.listdir(spool)
                if name.endswith(".json")
            )
            with open(message_path, encoding="utf-8") as stream:
                message = json.load(stream)
        payload_size = len(json.dumps(
            {"title": message["title"], "body": message["body"]}
        ).encode("utf-8"))
        self.assertLessEqual(
            payload_size, self.module.MAX_PUBLISH_PAYLOAD_BYTES
        )
        self.assertTrue(message["body"].endswith(self.module.TRUNCATION_SUFFIX))

    def test_does_not_queue_for_unregistered_user(self):
        with tempfile.TemporaryDirectory() as spool:
            with mock.patch.object(self.module, "log"):
                queued = self.module.queue_message(
                    self.registry,
                    [],
                    {"SLURM_JOB_USER": "bob"},
                    spool_path=spool,
                )
            self.assertFalse(queued)
            self.assertEqual(os.listdir(spool), [])

    def test_queue_capacity_limit_drops_new_message_without_blocking_slurm(self):
        with tempfile.TemporaryDirectory() as spool:
            with open(os.path.join(spool, "existing.json"), "w", encoding="utf-8") as stream:
                stream.write("{}")
            with mock.patch.object(self.module, "MAX_QUEUED_MESSAGES", 1), mock.patch.object(
                self.module, "log"
            ) as log:
                queued = self.module.queue_message(
                    self.registry,
                    [],
                    {
                        "SLURM_JOB_USER": "alice",
                        "SLURM_JOB_ID": "45",
                        "SLURM_JOB_MAIL_TYPE": "BEGIN",
                    },
                    spool_path=spool,
                )
            self.assertFalse(queued)
            self.assertEqual(
                [name for name in os.listdir(spool) if name.endswith(".json")],
                ["existing.json"],
            )
            log.assert_called_once()

    def test_disabled_registry_is_a_noop(self):
        self.registry["config"]["enabled"] = False
        with tempfile.TemporaryDirectory() as spool:
            queued = self.module.queue_message(self.registry, [], {}, spool_path=spool)
            self.assertFalse(queued)
            self.assertEqual(os.listdir(spool), [])


class SlurmOciWorkerTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("slurm_oci_worker_test", "slurm_oci_notify_worker.py")
        self.now = 1_700_000_000
        self.message = {
            "version": 1,
            "id": "message-id",
            "created_at": self.now,
            "expires_at": self.now + 7200,
            "next_attempt_at": self.now,
            "attempts": 0,
            "region": "ap-tokyo-1",
            "topic_id": "ocid1.onstopic.oc1.ap-tokyo-1.example",
            "username": "alice",
            "job_id": "42",
            "mail_type": "END",
            "title": "finished",
            "body": "done",
        }

    def write_message(self, spool):
        path = os.path.join(spool, "message-id.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(self.message, stream)
        return path

    def test_publishes_with_instance_principal_and_removes_message(self):
        with tempfile.TemporaryDirectory() as spool:
            path = self.write_message(spool)
            result = SimpleNamespace(returncode=0, stdout="{}", stderr="")
            command_input = {}

            def publish_success(command, **kwargs):
                input_uri = command[command.index("--from-json") + 1]
                with open(input_uri[len("file://"):], encoding="utf-8") as stream:
                    command_input.update(json.load(stream))
                return result

            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(self.module.subprocess, "run", side_effect=publish_success) as run, mock.patch.object(
                self.module, "log"
            ):
                count = self.module.process_queue(spool, now=self.now, executable="/test/oci")
            self.assertEqual(count, 1)
            self.assertFalse(os.path.exists(path))
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["/test/oci", "ons", "message", "publish"])
            self.assertIn("--from-json", command)
            self.assertIn("instance_principal", command)
            self.assertIn("ap-tokyo-1", command)
            self.assertNotIn("finished", command)
            self.assertNotIn("done", command)
            self.assertEqual(command_input["topicId"], self.message["topic_id"])
            self.assertEqual(command_input["title"], "finished")
            self.assertEqual(command_input["body"], "done")

    def test_failed_publish_is_retained_for_retry(self):
        with tempfile.TemporaryDirectory() as spool:
            path = self.write_message(spool)
            result = SimpleNamespace(returncode=1, stdout="", stderr="temporary failure")
            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(self.module.subprocess, "run", return_value=result), mock.patch.object(
                self.module, "log"
            ):
                self.module.process_queue(spool, now=self.now, executable="/test/oci")
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as stream:
                retry = json.load(stream)
            self.assertEqual(retry["attempts"], 1)
            self.assertEqual(retry["next_attempt_at"], self.now + 60)

    def test_expired_message_is_not_published(self):
        self.message["expires_at"] = self.now
        with tempfile.TemporaryDirectory() as spool:
            path = self.write_message(spool)
            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(self.module.subprocess, "run") as run, mock.patch.object(
                self.module, "log"
            ):
                count = self.module.process_queue(
                    spool, now=self.now, executable="/test/oci"
                )
            self.assertEqual(count, 1)
            self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(os.path.join(spool, "failed", "message-id.json")))
            run.assert_not_called()

    def test_discards_queued_message_after_user_is_removed(self):
        with tempfile.TemporaryDirectory() as spool:
            path = self.write_message(spool)
            with mock.patch.object(self.module, "load_active_topics", return_value={}), mock.patch.object(
                self.module.subprocess, "run"
            ) as run, mock.patch.object(self.module, "log"):
                self.module.process_queue(spool, now=self.now, executable="/test/oci")
            self.assertFalse(os.path.exists(path))
            run.assert_not_called()

    def test_retains_queued_message_when_registry_is_unavailable(self):
        with tempfile.TemporaryDirectory() as spool:
            path = self.write_message(spool)
            with mock.patch.object(
                self.module, "load_active_topics", return_value=None
            ), mock.patch.object(self.module.subprocess, "run") as run, mock.patch.object(
                self.module, "log"
            ):
                with self.assertRaisesRegex(RuntimeError, "temporarily unavailable"):
                    self.module.process_queue(
                        spool, now=self.now, executable="/test/oci"
                    )
            self.assertTrue(os.path.exists(path))
            run.assert_not_called()

    def test_invalid_message_is_quarantined_without_blocking_later_messages(self):
        with tempfile.TemporaryDirectory() as spool:
            invalid_path = os.path.join(spool, "00-invalid.json")
            with open(invalid_path, "w", encoding="utf-8") as stream:
                json.dump([], stream)
            valid_path = self.write_message(spool)
            result = SimpleNamespace(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(
                self.module.subprocess, "run", return_value=result
            ) as run, mock.patch.object(self.module, "log"):
                count = self.module.process_queue(
                    spool, now=self.now, executable="/test/oci"
                )
            self.assertEqual(count, 2)
            self.assertTrue(os.path.exists(os.path.join(spool, "failed", "00-invalid.json")))
            self.assertFalse(os.path.exists(valid_path))
            run.assert_called_once()

    def test_housekeeping_does_not_consume_publish_attempt_limit(self):
        with tempfile.TemporaryDirectory() as spool:
            for index in range(12):
                invalid_path = os.path.join(spool, "{:02d}-invalid.json".format(index))
                with open(invalid_path, "w", encoding="utf-8") as stream:
                    json.dump([], stream)
                os.utime(invalid_path, (80 + index, 80 + index))
            valid_path = self.write_message(spool)
            os.utime(valid_path, (100, 100))
            result = SimpleNamespace(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(
                self.module.subprocess, "run", return_value=result
            ) as run, mock.patch.object(self.module, "log"):
                count = self.module.process_queue(
                    spool, now=self.now, executable="/test/oci"
                )
            self.assertEqual(count, 13)
            self.assertFalse(os.path.exists(valid_path))
            run.assert_called_once()

    def test_limits_publish_attempts_but_leaves_remaining_messages_queued(self):
        with tempfile.TemporaryDirectory() as spool:
            for index in range(11):
                message = dict(
                    self.message,
                    id="message-{:02d}".format(index),
                    job_id=str(index),
                )
                path = os.path.join(spool, "message-{:02d}.json".format(index))
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump(message, stream)
                os.utime(path, (80 + index, 80 + index))
            result = SimpleNamespace(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(
                self.module.subprocess, "run", return_value=result
            ) as run, mock.patch.object(self.module, "log"):
                count = self.module.process_queue(
                    spool,
                    now=self.now,
                    executable="/test/oci",
                    clock=lambda: 100.0,
                    sleeper=lambda _delay: None,
                )
            self.assertEqual(count, self.module.MAX_PUBLISH_ATTEMPTS_PER_RUN)
            self.assertEqual(run.call_count, self.module.MAX_PUBLISH_ATTEMPTS_PER_RUN)
            queued = [name for name in os.listdir(spool) if name.endswith(".json")]
            self.assertEqual(queued, ["message-10.json"])

    def test_rate_limit_persists_across_worker_runs(self):
        current_time = [100.0]
        sleeps = []

        def clock():
            return current_time[0]

        def sleeper(delay):
            sleeps.append(delay)
            current_time[0] += delay

        result = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        with tempfile.TemporaryDirectory() as spool, mock.patch.object(
            self.module,
            "load_active_topics",
            return_value={"alice": self.message["topic_id"]},
        ), mock.patch.object(
            self.module.subprocess, "run", return_value=result
        ), mock.patch.object(self.module, "log"):
            self.write_message(spool)
            self.module.process_queue(
                spool,
                now=self.now,
                executable="/test/oci",
                clock=clock,
                sleeper=sleeper,
            )
            self.message["id"] = "second-message"
            second_path = os.path.join(spool, "second-message.json")
            with open(second_path, "w", encoding="utf-8") as stream:
                json.dump(self.message, stream)
            self.module.process_queue(
                spool,
                now=self.now,
                executable="/test/oci",
                clock=clock,
                sleeper=sleeper,
            )

        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(
            sleeps[0], self.module.MIN_PUBLISH_INTERVAL_SECONDS
        )

    def test_queue_is_processed_by_enqueue_age_not_uuid_filename(self):
        current_time = [100.0]
        published = []

        def clock():
            return current_time[0]

        def sleeper(delay):
            current_time[0] += delay

        with tempfile.TemporaryDirectory() as spool:
            newer = dict(self.message, id="newer", job_id="newer")
            older = dict(self.message, id="older", job_id="older")
            newer_path = os.path.join(spool, "00-newer.json")
            older_path = os.path.join(spool, "zz-older.json")
            for path, message in ((newer_path, newer), (older_path, older)):
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump(message, stream)
            os.utime(older_path, (90, 90))
            os.utime(newer_path, (95, 95))
            with mock.patch.object(
                self.module,
                "load_active_topics",
                return_value={"alice": self.message["topic_id"]},
            ), mock.patch.object(
                self.module,
                "publish",
                side_effect=lambda message, executable=None, temp_directory=None: published.append(
                    message["job_id"]
                ),
            ), mock.patch.object(self.module, "log"):
                self.module.process_queue(
                    spool,
                    now=self.now,
                    executable="/test/oci",
                    clock=clock,
                    sleeper=sleeper,
                )
        self.assertEqual(published, ["older", "newer"])

class NotificationRegistrySeedTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("slurm_registry_seed_test", "slurm_notification_registry_seed.py")

    def test_bootstrap_merge_updates_opc_and_preserves_ldap_users(self):
        bootstrap = {
            "config": {
                "enabled": True,
                "region": "ap-tokyo-1",
                "compartment_id": "ocid1.compartment.example",
                "cluster_name": "trial",
                "cluster_scope_id": "scope",
                "auth": "instance_principal",
            },
            "bootstrap_user": {
                "username": "opc",
                "email": "admin@example.com",
                "topic_id": "ocid1.onstopic.opc",
                "subscription_id": "ocid1.onssubscription.opc",
            },
        }
        existing = {
            "config": {},
            "users": {
                "alice": {
                    "email": "alice@example.com",
                    "topic_id": "ocid1.onstopic.alice",
                    "subscription_id": "ocid1.onssubscription.alice",
                    "managed_by": "cluster-cli",
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            registry_path = os.path.join(directory, "slurm_notification_users.json")
            with open(registry_path, "w", encoding="utf-8") as stream:
                json.dump(existing, stream)
            self.module.merge_registry(registry_path, bootstrap)
            with open(registry_path, encoding="utf-8") as stream:
                registry = json.load(stream)
        self.assertIn("alice", registry["users"])
        self.assertEqual(registry["users"]["opc"]["email"], "admin@example.com")
        self.assertEqual(registry["users"]["opc"]["managed_by"], "terraform")
        self.assertEqual(registry["config"], bootstrap["config"])

    def test_bootstrap_merge_preserves_pending_cleanup_metadata(self):
        bootstrap = {
            "config": {
                "enabled": True,
                "region": "ap-tokyo-1",
                "compartment_id": "ocid1.compartment.example",
                "cluster_name": "trial",
                "cluster_scope_id": "scope",
                "auth": "instance_principal",
            },
            "bootstrap_user": {
                "username": "opc",
                "email": "admin@example.com",
                "topic_id": "ocid1.onstopic.opc",
                "subscription_id": "ocid1.onssubscription.opc",
            },
        }
        pending = [{"username": "old-user", "topic_id": "ocid1.onstopic.old"}]
        existing = {"config": {"pending_cleanup": pending}, "users": {}}
        with tempfile.TemporaryDirectory() as directory:
            registry_path = os.path.join(directory, "slurm_notification_users.json")
            with open(registry_path, "w", encoding="utf-8") as stream:
                json.dump(existing, stream)
            self.module.merge_registry(registry_path, bootstrap)
            with open(registry_path, encoding="utf-8") as stream:
                registry = json.load(stream)
        self.assertEqual(registry["config"]["pending_cleanup"], pending)

    def test_disable_preserves_users_and_marks_config_disabled(self):
        existing = {
            "config": {"enabled": True, "region": "ap-tokyo-1"},
            "users": {"alice": {"topic_id": "ocid1.onstopic.alice"}},
        }
        with tempfile.TemporaryDirectory() as directory:
            registry_path = os.path.join(directory, "slurm_notification_users.json")
            with open(registry_path, "w", encoding="utf-8") as stream:
                json.dump(existing, stream)
            os.chmod(registry_path, 0o600)
            original_owner = (os.stat(registry_path).st_uid, os.stat(registry_path).st_gid)
            self.module.disable_registry(registry_path)
            with open(registry_path, encoding="utf-8") as stream:
                registry = json.load(stream)
            final_mode = os.stat(registry_path).st_mode & 0o777
            final_owner = (os.stat(registry_path).st_uid, os.stat(registry_path).st_gid)
        self.assertFalse(registry["config"]["enabled"])
        self.assertIn("alice", registry["users"])
        self.assertEqual(final_mode, 0o600)
        self.assertEqual(final_owner, original_owner)


if __name__ == "__main__":
    unittest.main()
