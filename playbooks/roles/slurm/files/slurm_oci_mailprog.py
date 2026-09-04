#!/usr/bin/env python3
"""Slurm MailProg adapter that durably queues an OCI Notifications message."""

import json
import os
import re
import shutil
import sys
import syslog
import tempfile
import time
import uuid


REGISTRY_PATH = "/opt/oci-hpc/conf/slurm_notification_users.json"
SPOOL_PATH = "/var/spool/slurm-oci-notify"
MAX_BODY_BYTES = 60 * 1024
MAX_TITLE_BYTES = 512
MAX_PUBLISH_PAYLOAD_BYTES = 60 * 1024
MAX_QUEUED_MESSAGES = 1200
MIN_FREE_SPOOL_BYTES = 256 * 1024 * 1024
TRUNCATION_SUFFIX = "\n\n[message truncated by slurm-oci-mailprog]"
SAFE_EVENT = re.compile(r"^[A-Z0-9_*,-]+$")
EVENT_ALIASES = {
    "BEGAN": "BEGIN",
    "ENDED": "END",
    "FAILED": "FAIL",
    "REQUEUED": "REQUEUE",
    "REACHED TIME LIMIT": "TIME_LIMIT",
    "REACHED 90% OF TIME LIMIT": "TIME_LIMIT_90",
    "REACHED 80% OF TIME LIMIT": "TIME_LIMIT_80",
    "REACHED 50% OF TIME LIMIT": "TIME_LIMIT_50",
    "INVALID DEPENDENCY": "INVALID_DEPEND",
    "STAGEOUT/TEARDOWN": "STAGE_OUT",
}


def log(message):
    syslog.openlog("slurm-oci-mailprog", syslog.LOG_PID, syslog.LOG_DAEMON)
    syslog.syslog(syslog.LOG_WARNING, message)


def load_registry(path=REGISTRY_PATH):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError) as error:
        log("notification registry unavailable: {}".format(error))
        return None
    return value if isinstance(value, dict) else None


def extract_subject(arguments):
    for index, argument in enumerate(arguments):
        if argument in ("-s", "--subject") and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith("--subject="):
            return argument.split("=", 1)[1]
    return ""


def sanitize_title(title, event, job_id):
    title = " ".join(str(title).replace("\r", " ").replace("\n", " ").split())
    if not title:
        title = "[Slurm] job {} {}".format(job_id or "unknown", event or "notification")
    encoded = title.encode("utf-8")
    if len(encoded) > MAX_TITLE_BYTES:
        title = encoded[:MAX_TITLE_BYTES].decode("utf-8", errors="ignore")
    return title


def read_body():
    content = sys.stdin.buffer.read(MAX_BODY_BYTES + 1)
    truncated = len(content) > MAX_BODY_BYTES
    content = content[:MAX_BODY_BYTES].decode("utf-8", errors="replace")
    if truncated:
        content += TRUNCATION_SUFFIX
    return content


def publish_payload_size(title, body):
    # Match the OCI Python SDK's default application/json serialization.
    return len(json.dumps({"title": title, "body": body}).encode("utf-8"))


def fit_body_to_publish_limit(title, body):
    if publish_payload_size(title, body) <= MAX_PUBLISH_PAYLOAD_BYTES:
        return body

    low = 0
    high = len(body)
    best = TRUNCATION_SUFFIX
    while low <= high:
        midpoint = (low + high) // 2
        candidate = body[:midpoint] + TRUNCATION_SUFFIX
        if publish_payload_size(title, candidate) <= MAX_PUBLISH_PAYLOAD_BYTES:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def queue_has_capacity(spool_path):
    queued_messages = 0
    with os.scandir(spool_path) as entries:
        for entry in entries:
            if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False):
                queued_messages += 1
                if queued_messages >= MAX_QUEUED_MESSAGES:
                    log("notification queue limit reached; dropping new notification")
                    return False
    if shutil.disk_usage(spool_path).free < MIN_FREE_SPOOL_BYTES:
        log("notification spool has insufficient free space; dropping new notification")
        return False
    return True


def normalize_event(value):
    value = str(value or "").strip()
    normalized = EVENT_ALIASES.get(value.upper(), value.upper())
    return normalized if normalized and SAFE_EVENT.match(normalized) else "UNKNOWN"


def build_fallback_body(config, environ, username, event, job_id):
    fields = (
        ("Cluster", config.get("cluster_name")),
        ("Job ID", job_id),
        ("Job name", environ.get("SLURM_JOB_NAME")),
        ("User", username),
        ("Event", event),
        ("State", environ.get("SLURM_JOB_STATE")),
        ("Partition", environ.get("SLURM_JOB_PARTITION")),
        ("Nodes", environ.get("SLURM_JOB_NODELIST")),
        ("Queued time", environ.get("SLURM_JOB_QUEUED_TIME")),
        ("Run time", environ.get("SLURM_JOB_RUN_TIME")),
        ("Exit code", environ.get("SLURM_JOB_EXIT_CODE_MAX")),
        ("Termination signal", environ.get("SLURM_JOB_TERM_SIGNAL_MAX")),
        ("Working directory", environ.get("SLURM_JOB_WORK_DIR")),
        ("Standard output", environ.get("SLURM_JOB_STDOUT")),
        ("Standard error", environ.get("SLURM_JOB_STDERR")),
    )
    lines = ["{}: {}".format(label, value) for label, value in fields if value not in (None, "")]
    return "\n".join(lines) or "Slurm job notification"


def queue_message(registry, arguments, environ, spool_path=SPOOL_PATH):
    config = registry.get("config", {})
    users = registry.get("users", {})
    if not config.get("enabled") or not isinstance(users, dict):
        return False

    username = environ.get("SLURM_JOB_USER", "")
    user = users.get(username, {})
    topic_id = user.get("topic_id") if isinstance(user, dict) else None
    if not topic_id:
        log("no notification topic registered for Slurm user {}".format(username or "unknown"))
        return False


    os.makedirs(spool_path, mode=0o2770, exist_ok=True)
    if not queue_has_capacity(spool_path):
        return False

    event = normalize_event(environ.get("SLURM_JOB_MAIL_TYPE", ""))
    job_id = environ.get("SLURM_JOB_ID") or environ.get("SLURM_JOBID", "")
    now = int(time.time())
    body = read_body()
    if not body.strip():
        body = build_fallback_body(config, environ, username, event, job_id)
    title = sanitize_title(extract_subject(arguments), event, job_id)
    body = fit_body_to_publish_limit(title, body)
    message = {
        "version": 1,
        "id": str(uuid.uuid4()),
        "created_at": now,
        "expires_at": now + 7200,
        "next_attempt_at": now,
        "attempts": 0,
        "region": config.get("region", ""),
        "topic_id": topic_id,
        "username": username,
        "job_id": job_id,
        "mail_type": event,
        "title": title,
        "body": body,
    }

    descriptor, temporary_path = tempfile.mkstemp(prefix=".notify-", dir=spool_path)
    final_path = os.path.join(spool_path, "{}.json".format(message["id"]))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(message, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            os.fchmod(stream.fileno(), 0o640)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, final_path)
        directory_descriptor = os.open(spool_path, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return True


def main(arguments=None, environ=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    environ = os.environ if environ is None else environ
    registry = load_registry()
    if registry is None:
        return 0
    try:
        queue_message(registry, arguments, environ)
    except Exception as error:  # Mail delivery must never affect the job lifecycle.
        log("failed to queue notification: {}".format(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
