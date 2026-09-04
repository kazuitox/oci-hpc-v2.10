#!/usr/bin/env python3
"""Remove cluster-cli managed OCI Notifications Topics during destroy."""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time


OCI_TIMEOUT_SECONDS = 120
POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 2
MAX_ERROR_CHARS = 500
VALID_REGION = re.compile(r"^[a-z0-9-]+$")
VALID_DEPLOYMENT_ID = re.compile(r"^[0-9a-f]{32}$")
TOPIC_OCID_PREFIX = "ocid1.onstopic."


class CleanupError(RuntimeError):
    """Raised when cleanup cannot continue without risking another resource."""


def _topic_component(value, maximum_length=48):
    """Keep this identical to cluster-cli's deterministic Topic naming."""
    component = re.sub(r"[^a-z0-9_-]+", "-", str(value).lower()).strip("-_")
    return (component or "user")[:maximum_length]


def notification_topic_name(config, user):
    identity = "{}:{}".format(config["cluster_scope_id"], user)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return "slurm-{}-{}-{}".format(
        _topic_component(config["cluster_name"]),
        _topic_component(user),
        suffix,
    )


def decode_config(encoded):
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, TypeError) as error:
        raise CleanupError("cleanup configuration is not valid base64 JSON") from error

    if not isinstance(config, dict):
        raise CleanupError("cleanup configuration must be a JSON object")
    for field in (
        "region",
        "compartment_id",
        "cluster_name",
        "cluster_scope_id",
        "deployment_id",
        "registry_path",
    ):
        if not isinstance(config.get(field), str) or not config[field]:
            raise CleanupError("cleanup configuration field '{}' is invalid".format(field))
    if VALID_REGION.fullmatch(config["region"]) is None:
        raise CleanupError("cleanup configuration region is invalid")
    if VALID_DEPLOYMENT_ID.fullmatch(config["deployment_id"]) is None:
        raise CleanupError("cleanup configuration deployment_id is invalid")
    if not config["compartment_id"].startswith(
        ("ocid1.compartment.", "ocid1.tenancy.")
    ):
        raise CleanupError("cleanup configuration compartment_id is invalid")
    if (
        not os.path.isabs(config["registry_path"])
        or os.path.normpath(config["registry_path"]) != config["registry_path"]
    ):
        raise CleanupError("cleanup configuration registry_path is invalid")

    protected = config.get("protected_topic_ids")
    if not isinstance(protected, list):
        raise CleanupError("cleanup configuration protected_topic_ids must be a list")
    protected_ids = set()
    for topic_id in protected:
        if not isinstance(topic_id, str) or not topic_id.startswith(TOPIC_OCID_PREFIX):
            raise CleanupError("cleanup configuration contains an invalid protected Topic OCID")
        protected_ids.add(topic_id)
    config["protected_topic_ids"] = protected_ids
    return config


def _scope_pair(value, context):
    if not isinstance(value, dict):
        raise CleanupError("{} must be an object".format(context))
    scope = {}
    for field in ("cluster_name", "cluster_scope_id"):
        field_value = value.get(field)
        if not isinstance(field_value, str) or not field_value:
            raise CleanupError("{} field '{}' is invalid".format(context, field))
        scope[field] = field_value
    return scope


def _scope_deployment_identity(scope, context):
    try:
        scope_name, random_name, compartment_hash = scope[
            "cluster_scope_id"
        ].rsplit(":", 2)
    except ValueError as error:
        raise CleanupError("{} has an invalid cluster_scope_id".format(context)) from error
    if scope_name != scope["cluster_name"][:128] or not random_name:
        raise CleanupError("{} does not match its cluster_name".format(context))
    if re.fullmatch(r"[0-9a-f]{12}", compartment_hash) is None:
        raise CleanupError("{} has an invalid compartment hash".format(context))
    return random_name, compartment_hash


def _registry_topic_id(entry, context, protected_ids, required):
    if not isinstance(entry, dict):
        raise CleanupError("{} must be an object".format(context))
    if entry.get("managed_by") != "cluster-cli":
        return None

    topic_id = entry.get("topic_id")
    if topic_id in (None, "") and not required:
        return None
    if (
        not isinstance(topic_id, str)
        or not topic_id.startswith(TOPIC_OCID_PREFIX)
        or topic_id == TOPIC_OCID_PREFIX
        or any(character.isspace() for character in topic_id)
    ):
        raise CleanupError("{} contains an invalid Topic OCID".format(context))
    if topic_id in protected_ids:
        return None
    return topic_id


def load_cleanup_metadata(config):
    """Load Topic ownership scopes and registered cluster-cli Topic OCIDs."""
    current_scope = _scope_pair(config, "cleanup configuration")
    deployment_identity = _scope_deployment_identity(
        current_scope, "cleanup configuration"
    )
    scopes = [current_scope]
    seen = {(current_scope["cluster_name"], current_scope["cluster_scope_id"])}

    try:
        with open(config["registry_path"], "r", encoding="utf-8") as stream:
            registry = json.load(stream)
    except FileNotFoundError:
        return scopes, set()
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise CleanupError("notification registry could not be read") from error

    if not isinstance(registry, dict) or not isinstance(registry.get("config"), dict):
        raise CleanupError("notification registry is malformed")
    registry_config = registry["config"]
    registry_deployment_id = registry_config.get("deployment_id")
    if (
        not isinstance(registry_deployment_id, str)
        or VALID_DEPLOYMENT_ID.fullmatch(registry_deployment_id) is None
    ):
        raise CleanupError("notification registry deployment_id is invalid")
    if registry_deployment_id != config["deployment_id"]:
        raise CleanupError("notification registry belongs to another deployment")
    registry_scope = _scope_pair(registry_config, "notification registry config")
    if (
        _scope_deployment_identity(
            registry_scope, "notification registry config"
        )
        != deployment_identity
    ):
        raise CleanupError(
            "notification registry config belongs to another deployment"
        )
    registry_identity = (
        registry_scope["cluster_name"],
        registry_scope["cluster_scope_id"],
    )
    if registry_identity not in seen:
        seen.add(registry_identity)
        scopes.append(registry_scope)

    history = registry_config.get("cleanup_scopes", [])
    if not isinstance(history, list):
        raise CleanupError("notification registry cleanup_scopes must be a list")
    for index, entry in enumerate(history):
        context = "notification registry cleanup_scopes[{}]".format(index)
        scope = _scope_pair(
            entry,
            context,
        )
        if _scope_deployment_identity(scope, context) != deployment_identity:
            raise CleanupError("{} belongs to another deployment".format(context))
        identity = (scope["cluster_name"], scope["cluster_scope_id"])
        if identity not in seen:
            seen.add(identity)
            scopes.append(scope)

    users = registry.get("users")
    if not isinstance(users, dict):
        raise CleanupError("notification registry users must be an object")
    known_topic_ids = set()
    for username, entry in users.items():
        if not isinstance(username, str) or not username:
            raise CleanupError("notification registry has an invalid username")
        topic_id = _registry_topic_id(
            entry,
            "notification registry user '{}'".format(username),
            config["protected_topic_ids"],
            required=True,
        )
        if topic_id is not None:
            known_topic_ids.add(topic_id)

    pending = registry_config.get("pending_cleanup", [])
    if not isinstance(pending, list):
        raise CleanupError("notification registry pending_cleanup must be a list")
    for index, entry in enumerate(pending):
        topic_id = _registry_topic_id(
            entry,
            "notification registry pending_cleanup[{}]".format(index),
            config["protected_topic_ids"],
            required=False,
        )
        if topic_id is not None:
            known_topic_ids.add(topic_id)
    return scopes, known_topic_ids


def load_cleanup_scopes(config):
    """Compatibility wrapper for callers interested only in scope history."""
    scopes, _ = load_cleanup_metadata(config)
    return scopes


def find_oci():
    home = os.path.expanduser("~")
    candidates = (
        os.path.join(home, ".local", "bin", "oci"),
        os.path.join(home, "bin", "oci"),
        "/usr/local/bin/oci",
        "/usr/bin/oci",
    )
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    executable = shutil.which("oci")
    if executable:
        return executable
    raise CleanupError("OCI CLI executable was not found")


def run_oci(config, arguments, executable=None):
    executable = executable or find_oci()
    command = [executable] + arguments + [
        "--auth",
        "instance_principal",
        "--region",
        config["region"],
        "--max-retries",
        "0",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=OCI_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CleanupError(
            "OCI CLI timed out after {} seconds".format(OCI_TIMEOUT_SECONDS)
        ) from error
    except OSError as error:
        raise CleanupError("unable to execute OCI CLI: {}".format(error)) from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "OCI CLI failed").replace("\n", " ")
        raise CleanupError(detail[:MAX_ERROR_CHARS])
    return result


def _parse_topic_list(stdout):
    output = (stdout or "").strip()
    if not output:
        raise CleanupError("OCI CLI returned an empty Topic list response")
    try:
        payload = json.loads(output)
    except (TypeError, ValueError) as error:
        raise CleanupError("OCI CLI returned malformed Topic list JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise CleanupError("OCI CLI returned malformed Topic list output")

    topics = payload["data"]
    seen_ids = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise CleanupError("OCI CLI returned a malformed Topic entry")
        topic_id = topic.get("topic-id")
        if not isinstance(topic_id, str) or not topic_id.startswith(TOPIC_OCID_PREFIX):
            raise CleanupError("OCI CLI returned a malformed Topic OCID")
        if topic_id in seen_ids:
            raise CleanupError("OCI CLI returned a duplicate Topic OCID")
        seen_ids.add(topic_id)
    return topics


def list_topics(config, executable=None):
    result = run_oci(
        config,
        [
            "ons",
            "topic",
            "list",
            "--compartment-id",
            config["compartment_id"],
            "--all",
            "--output",
            "json",
            "--query",
            "@",
        ],
        executable=executable,
    )
    return _parse_topic_list(result.stdout)


def _owned_topic_ids(config, topics, scopes=None):
    scopes = scopes or [_scope_pair(config, "cleanup configuration")]
    deployment_scope_identity = _scope_deployment_identity(
        _scope_pair(config, "cleanup configuration"),
        "cleanup configuration",
    )
    ownership_tags = [
        {
            "managed_by": "cluster-cli",
            "notification_scope": scope["cluster_scope_id"],
            "cluster_name": scope["cluster_name"],
            "parent_cluster": scope["cluster_name"],
        }
        for scope in scopes
    ]
    protected_ids = config["protected_topic_ids"]
    delete_ids = []
    wait_ids = []
    for topic in topics:
        topic_id = topic["topic-id"]
        # Terraform-owned resources are protected by OCID, independently of
        # their mutable tags, name, or lifecycle state.
        if topic_id in protected_ids:
            continue

        tags = topic.get("freeform-tags")
        if tags is None:
            tags = {}
        elif not isinstance(tags, dict):
            raise CleanupError("OCI CLI returned malformed Topic tags")
        matching_scope = None
        if "notification_deployment_id" in tags:
            if tags.get("notification_deployment_id") != config["deployment_id"]:
                # A deployment tag takes precedence over legacy scope matching.
                # Never delete a Topic explicitly owned by another deployment.
                continue
            if tags.get("managed_by") != "cluster-cli":
                raise CleanupError(
                    "deployment-tagged Topic {} has invalid ownership tags".format(
                        topic_id
                    )
                )
            matching_scope = _scope_pair(
                {
                    "cluster_name": tags.get("cluster_name"),
                    "cluster_scope_id": tags.get("notification_scope"),
                },
                "deployment-tagged Topic {}".format(topic_id),
            )
            if tags.get("parent_cluster") != matching_scope["cluster_name"]:
                raise CleanupError(
                    "deployment-tagged Topic {} has invalid cluster tags".format(
                        topic_id
                    )
                )
            if (
                _scope_deployment_identity(
                    matching_scope,
                    "deployment-tagged Topic {}".format(topic_id),
                )
                != deployment_scope_identity
            ):
                raise CleanupError(
                    "deployment-tagged Topic {} has an incompatible notification scope".format(
                        topic_id
                    )
                )
        else:
            # Topics created before notification_deployment_id was introduced
            # remain discoverable through the exact current/history scopes.
            for scope, expected_tags in zip(scopes, ownership_tags):
                if all(
                    tags.get(key) == value for key, value in expected_tags.items()
                ):
                    matching_scope = scope
                    break
        if matching_scope is None:
            continue

        if not isinstance(topic.get("name"), str):
            raise CleanupError("OCI CLI returned a malformed Topic name")
        username = tags.get("slurm_user")
        if not isinstance(username, str) or not username.strip():
            raise CleanupError(
                "owned Topic {} has no valid slurm_user tag".format(topic["topic-id"])
            )
        expected_name = notification_topic_name(matching_scope, username)
        if topic["name"] != expected_name:
            raise CleanupError(
                "owned Topic {} does not match its deterministic name".format(
                    topic["topic-id"]
                )
            )

        lifecycle_state = topic.get("lifecycle-state")
        if lifecycle_state not in ("ACTIVE", "CREATING", "DELETING"):
            raise CleanupError(
                "owned Topic {} has an invalid lifecycle state".format(topic_id)
            )
        wait_ids.append(topic_id)
        if lifecycle_state != "DELETING":
            delete_ids.append(topic_id)
    return delete_ids, wait_ids


def _validate_known_topics(known_topic_ids, topics, owned_topic_ids):
    listed_topic_ids = {topic["topic-id"] for topic in topics}
    drifted_topic_ids = (
        known_topic_ids.intersection(listed_topic_ids) - set(owned_topic_ids)
    )
    if drifted_topic_ids:
        raise CleanupError(
            "registered cluster-cli Topic(s) failed ownership validation: {}".format(
                ", ".join(sorted(drifted_topic_ids))
            )
        )


def _delete_topic(config, topic_id, executable=None):
    run_oci(
        config,
        [
            "ons",
            "topic",
            "delete",
            "--topic-id",
            topic_id,
            "--force",
        ],
        executable=executable,
    )


def cleanup_topics(
    config,
    executable=None,
    sleeper=None,
    poll_attempts=POLL_ATTEMPTS,
    poll_interval=POLL_INTERVAL_SECONDS,
):
    """Delete owned, unprotected Topics and confirm their eventual absence."""
    sleeper = time.sleep if sleeper is None else sleeper
    scopes, known_topic_ids = load_cleanup_metadata(config)
    topics = list_topics(config, executable=executable)
    delete_ids, wait_ids = _owned_topic_ids(config, topics, scopes=scopes)
    _validate_known_topics(known_topic_ids, topics, wait_ids)

    # Candidate discovery and validation finishes before the first mutation.
    for topic_id in delete_ids:
        _delete_topic(config, topic_id, executable=executable)

    remaining = set(wait_ids)
    observed_owned = set(wait_ids)
    delete_requested = set(delete_ids)
    for attempt in range(poll_attempts):
        current_topics = list_topics(config, executable=executable)
        # Apply the same ownership/name checks on every read.  A concurrently
        # introduced malformed owned Topic must not be silently overlooked.
        current_delete_ids, current_owned_ids = _owned_topic_ids(
            config, current_topics, scopes=scopes
        )
        _validate_known_topics(known_topic_ids, current_topics, current_owned_ids)
        current_ids = {topic["topic-id"] for topic in current_topics}
        remaining.intersection_update(current_ids)
        remaining.update(current_owned_ids)
        observed_owned.update(current_owned_ids)

        # A Topic may be created concurrently after initial discovery. Request
        # deletion once, then keep it in the finite absence-confirmation loop.
        for topic_id in current_delete_ids:
            if topic_id not in delete_requested:
                _delete_topic(config, topic_id, executable=executable)
                delete_requested.add(topic_id)
        if not remaining:
            return len(observed_owned)
        if attempt + 1 < poll_attempts:
            sleeper(poll_interval)
    raise CleanupError(
        "timed out waiting for {} Topic(s) to be deleted: {}".format(
            len(remaining), ", ".join(sorted(remaining))
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Delete cluster-cli managed OCI Notifications Topics"
    )
    parser.add_argument("--config-base64", required=True)
    args = parser.parse_args(argv)
    try:
        config = decode_config(args.config_base64)
        deleted = cleanup_topics(config)
    except CleanupError as error:
        print("Error: {}".format(error), file=sys.stderr)
        return 1
    print("Deleted {} OCI Notifications Topic(s).".format(deleted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
