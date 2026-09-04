#!/usr/bin/env python3
"""Deliver queued Slurm notifications with bounded retry and no job impact."""

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import syslog
import tempfile
import time


SPOOL_PATH = "/var/spool/slurm-oci-notify"
REGISTRY_PATH = "/opt/oci-hpc/conf/slurm_notification_users.json"
MAX_PUBLISH_ATTEMPTS_PER_RUN = 10
MAX_ERROR_CHARS = 500
MIN_PUBLISH_INTERVAL_SECONDS = 6.1
MAX_TITLE_BYTES = 512
MAX_PUBLISH_PAYLOAD_BYTES = 60 * 1024
VALID_REGION = re.compile(r"^[a-z0-9-]+$")


def log(priority, message):
    syslog.openlog("slurm-oci-notify", syslog.LOG_PID, syslog.LOG_DAEMON)
    syslog.syslog(priority, message)


def atomic_write(path, value):
    descriptor, temporary_path = tempfile.mkstemp(prefix=".retry-", dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o640)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def find_oci():
    executable = shutil.which("oci")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/oci", "/usr/bin/oci"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("OCI CLI executable was not found")


def load_active_topics(path=REGISTRY_PATH):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            registry = json.load(stream)
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(registry, dict):
        return None
    config = registry.get("config", {})
    users = registry.get("users", {})
    if not isinstance(config, dict) or not isinstance(users, dict):
        return None
    if not config.get("enabled"):
        return {}
    return {
        username: details.get("topic_id")
        for username, details in users.items()
        if isinstance(details, dict) and details.get("topic_id")
    }


def validate_message(message):
    if not isinstance(message, dict) or message.get("version") != 1:
        raise ValueError("invalid queued notification schema")
    for field in ("id", "region", "topic_id", "username", "job_id", "mail_type", "title", "body"):
        if not isinstance(message.get(field), str):
            raise ValueError("invalid queued notification field '{}'".format(field))
    for field in ("created_at", "expires_at", "next_attempt_at", "attempts"):
        value = message.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("invalid queued notification field '{}'".format(field))
    if message["expires_at"] < message["created_at"]:
        raise ValueError("queued notification expires before it was created")
    if not VALID_REGION.match(message["region"]):
        raise ValueError("invalid OCI region")
    if not message["topic_id"].startswith("ocid1.onstopic."):
        raise ValueError("invalid Notifications topic OCID")
    if len(message["title"].encode("utf-8")) > MAX_TITLE_BYTES:
        raise ValueError("queued notification title is too large")
    # Match the OCI Python SDK's default application/json serialization.
    payload_size = len(json.dumps(
        {"title": message["title"], "body": message["body"]}
    ).encode("utf-8"))
    if payload_size > MAX_PUBLISH_PAYLOAD_BYTES:
        raise ValueError("queued notification payload is too large")
    return message


def publish(message, executable=None, temp_directory=None):
    region = message.get("region", "")
    topic_id = message.get("topic_id", "")
    if not VALID_REGION.match(region):
        raise ValueError("invalid OCI region")
    if not topic_id.startswith("ocid1.onstopic."):
        raise ValueError("invalid Notifications topic OCID")
    executable = executable or find_oci()
    descriptor, input_path = tempfile.mkstemp(
        prefix=".publish-input-",
        suffix=".tmp",
        dir=temp_directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "topicId": topic_id,
                    "title": message.get("title", ""),
                    "body": message.get("body", ""),
                },
                stream,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        command = [
            executable,
            "ons",
            "message",
            "publish",
            "--from-json",
            "file://{}".format(input_path),
            "--auth",
            "instance_principal",
            "--region",
            region,
            "--max-retries",
            "0",
            "--connection-timeout",
            "5",
            "--read-timeout",
            "20",
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=30,
            check=False,
        )
    finally:
        if os.path.exists(input_path):
            try:
                os.unlink(input_path)
            except OSError as error:
                log(syslog.LOG_WARNING, "could not remove temporary OCI payload: {}".format(error))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "OCI CLI failed").replace("\n", " ")
        raise RuntimeError(detail[:MAX_ERROR_CHARS])


def mark_retry(path, message, now, error):
    message["attempts"] = int(message.get("attempts", 0)) + 1
    if now >= int(message.get("expires_at", now)):
        failed_directory = os.path.join(os.path.dirname(path), "failed")
        os.makedirs(failed_directory, mode=0o2770, exist_ok=True)
        os.replace(path, os.path.join(failed_directory, os.path.basename(path)))
        log(syslog.LOG_ERR, "notification {} expired after {} attempts: {}".format(
            message.get("id", "unknown"), message["attempts"], error
        ))
        return
    delay = min(3600, 60 * (2 ** min(message["attempts"] - 1, 6)))
    message["next_attempt_at"] = now + delay
    atomic_write(path, message)
    log(syslog.LOG_WARNING, "notification {} delivery failed; retry in {}s: {}".format(
        message.get("id", "unknown"), delay, error
    ))


def quarantine(path, error):
    failed_directory = os.path.join(os.path.dirname(path), "failed")
    os.makedirs(failed_directory, mode=0o2770, exist_ok=True)
    os.replace(path, os.path.join(failed_directory, os.path.basename(path)))
    log(syslog.LOG_ERR, "quarantined invalid notification {}: {}".format(
        os.path.basename(path), error
    ))


def expire(path, message):
    failed_directory = os.path.join(os.path.dirname(path), "failed")
    os.makedirs(failed_directory, mode=0o2770, exist_ok=True)
    os.replace(path, os.path.join(failed_directory, os.path.basename(path)))
    log(syslog.LOG_NOTICE, "notification {} expired before delivery".format(
        message.get("id", "unknown")
    ))


def read_last_publish_at(lock):
    lock.seek(0)
    value = lock.read().strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def wait_for_publish_slot(lock, clock, sleeper):
    last_publish_at = read_last_publish_at(lock)
    current_time = clock()
    if last_publish_at is None:
        return
    delay = min(
        MIN_PUBLISH_INTERVAL_SECONDS,
        max(0, MIN_PUBLISH_INTERVAL_SECONDS - (current_time - last_publish_at)),
    )
    if delay > 0:
        sleeper(delay)


def record_publish_attempt(lock, timestamp):
    lock.seek(0)
    lock.truncate()
    lock.write("{:.6f}\n".format(timestamp))
    lock.flush()
    os.fsync(lock.fileno())


def queued_message_names(spool_path):
    names = [name for name in os.listdir(spool_path) if name.endswith(".json")]

    def queue_age(name):
        try:
            return (os.stat(os.path.join(spool_path, name)).st_mtime_ns, name)
        except OSError:
            return (0, name)

    return sorted(names, key=queue_age)


def process_queue(
    spool_path=SPOOL_PATH,
    now=None,
    executable=None,
    clock=None,
    sleeper=None,
):
    fixed_now = None if now is None else int(now)
    clock = time.time if clock is None else clock
    sleeper = time.sleep if sleeper is None else sleeper
    os.makedirs(spool_path, mode=0o2770, exist_ok=True)
    lock_path = os.path.join(spool_path, ".worker.lock")
    processed = 0
    publish_attempts = 0
    with open(lock_path, "a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        active_topics = load_active_topics()
        if active_topics is None:
            raise RuntimeError("notification registry is temporarily unavailable")
        for name in queued_message_names(spool_path):
            path = os.path.join(spool_path, name)
            message = {}
            message_loaded = False
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    message = validate_message(json.load(stream))
                message_loaded = True
                message_now = int(time.time()) if fixed_now is None else fixed_now
                if message_now < message["next_attempt_at"]:
                    continue
                if message_now >= message["expires_at"]:
                    expire(path, message)
                    processed += 1
                    continue
                username = message.get("username", "")
                if active_topics.get(username) != message.get("topic_id"):
                    os.unlink(path)
                    log(syslog.LOG_NOTICE, "discarded notification for unregistered user {}".format(username))
                    processed += 1
                    continue
                if publish_attempts >= MAX_PUBLISH_ATTEMPTS_PER_RUN:
                    continue
                wait_for_publish_slot(lock, clock, sleeper)
                record_publish_attempt(lock, clock())
                publish_attempts += 1
                publish(
                    message,
                    executable=executable,
                    temp_directory=spool_path,
                )
                try:
                    os.unlink(path)
                except OSError as cleanup_error:
                    try:
                        failed_directory = os.path.join(os.path.dirname(path), "failed")
                        os.makedirs(failed_directory, mode=0o2770, exist_ok=True)
                        os.replace(
                            path,
                            os.path.join(failed_directory, os.path.basename(path) + ".delivered"),
                        )
                    except OSError as archive_error:
                        log(syslog.LOG_ERR, "could not remove delivered notification {}: {}; archive failed: {}".format(
                            name, cleanup_error, archive_error
                        ))
                    else:
                        log(syslog.LOG_WARNING, "archived delivered notification {} after unlink failed: {}".format(
                            name, cleanup_error
                        ))
                log(syslog.LOG_INFO, "delivered Slurm job {} event {} for user {}".format(
                    message.get("job_id", "unknown"), message.get("mail_type", "unknown"), username
                ))
            except (ValueError, json.JSONDecodeError, TypeError) as error:
                try:
                    quarantine(path, error)
                except OSError as quarantine_error:
                    log(syslog.LOG_ERR, "could not quarantine invalid notification {}: {}".format(
                        name, quarantine_error
                    ))
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                if isinstance(error, OSError) and not message_loaded:
                    log(syslog.LOG_WARNING, "could not read queued notification {}: {}".format(
                        name, error
                    ))
                    continue
                try:
                    retry_now = int(time.time()) if fixed_now is None else fixed_now
                    mark_retry(path, message, retry_now, error)
                except (OSError, TypeError, ValueError) as retry_error:
                    log(syslog.LOG_ERR, "could not retain failed notification {}: {}".format(name, retry_error))
            processed += 1
    return processed


def main():
    try:
        process_queue()
    except Exception as error:
        log(syslog.LOG_ERR, "notification worker failed: {}".format(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
