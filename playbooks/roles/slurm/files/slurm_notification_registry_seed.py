#!/usr/bin/env python3
"""Merge Terraform-managed bootstrap data into the runtime notification registry."""

import argparse
import fcntl
import json
import os
import stat
import tempfile


def notification_scope(config):
    """Return a validated cleanup-scope record, or None for legacy empty config."""
    cluster_name = config.get("cluster_name")
    cluster_scope_id = config.get("cluster_scope_id")
    if cluster_name is None and cluster_scope_id is None:
        return None
    if not isinstance(cluster_name, str) or not cluster_name:
        raise ValueError("notification registry cluster_name is invalid")
    if not isinstance(cluster_scope_id, str) or not cluster_scope_id:
        raise ValueError("notification registry cluster_scope_id is invalid")
    return {
        "cluster_name": cluster_name,
        "cluster_scope_id": cluster_scope_id,
    }


def cleanup_scope_history(config):
    """Validate and de-duplicate the recorded notification scope history."""
    history = config.get("cleanup_scopes", [])
    if not isinstance(history, list):
        raise ValueError("notification registry cleanup_scopes must be a list")

    result = []
    seen = set()
    for entry in history:
        if not isinstance(entry, dict):
            raise ValueError("notification registry has an invalid cleanup scope")
        scope = notification_scope(entry)
        if scope is None:
            raise ValueError("notification registry has an empty cleanup scope")
        identity = (scope["cluster_name"], scope["cluster_scope_id"])
        if identity not in seen:
            seen.add(identity)
            result.append(scope)
    return result


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
            return value if isinstance(value, dict) else default
    except FileNotFoundError:
        return default


def atomic_write(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    try:
        existing_stat = os.stat(path)
    except FileNotFoundError:
        existing_stat = None
    descriptor, temporary_path = tempfile.mkstemp(prefix=".slurm_notification_users.", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if existing_stat is None:
            os.chmod(temporary_path, 0o640)
        else:
            os.chmod(temporary_path, stat.S_IMODE(existing_stat.st_mode))
            os.chown(temporary_path, existing_stat.st_uid, existing_stat.st_gid)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def merge_registry(registry_path, bootstrap):
    lock_path = registry_path + ".lock"
    os.makedirs(os.path.dirname(registry_path), mode=0o755, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        registry = load_json(registry_path, {"config": {}, "users": {}})
        if not isinstance(registry.get("users"), dict):
            registry["users"] = {}
        config = registry.get("config", {})
        if not isinstance(config, dict):
            config = {}

        previous_deployment_id = config.get("deployment_id")
        next_deployment_id = bootstrap["config"].get("deployment_id")
        if (
            previous_deployment_id is not None
            and previous_deployment_id != next_deployment_id
        ):
            raise ValueError("notification registry belongs to another deployment")

        # Cluster names are mutable, while dynamically-created Topics keep the
        # tags and deterministic names from their creation scope. Preserve the
        # previous pair so the final destroy can identify those Topics without
        # deleting them during an ordinary update.
        history = cleanup_scope_history(config)
        previous_scope = notification_scope(config)
        next_scope = notification_scope(bootstrap["config"])
        history_identities = {
            (scope["cluster_name"], scope["cluster_scope_id"])
            for scope in history
        }
        if previous_scope is not None and previous_scope != next_scope:
            previous_identity = (
                previous_scope["cluster_name"],
                previous_scope["cluster_scope_id"],
            )
            if previous_identity not in history_identities:
                history.append(previous_scope)

        config.update(bootstrap["config"])
        if history:
            config["cleanup_scopes"] = history
        else:
            config.pop("cleanup_scopes", None)
        registry["config"] = config

        user = bootstrap["bootstrap_user"]
        username = user["username"]
        registry["users"][username] = {
            "email": user["email"],
            "topic_id": user["topic_id"],
            "subscription_id": user["subscription_id"],
            "managed_by": "terraform",
        }
        atomic_write(registry_path, registry)


def disable_registry(registry_path):
    lock_path = registry_path + ".lock"
    os.makedirs(os.path.dirname(registry_path), mode=0o755, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        registry = load_json(registry_path, {"config": {}, "users": {}})
        config = registry.get("config", {})
        if not isinstance(config, dict):
            config = {}
        config["enabled"] = False
        registry["config"] = config
        if not isinstance(registry.get("users"), dict):
            registry["users"] = {}
        atomic_write(registry_path, registry)


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--bootstrap-file")
    action.add_argument("--disable", action="store_true")
    parser.add_argument("--registry", required=True)
    args = parser.parse_args()

    if args.disable:
        disable_registry(args.registry)
        return

    bootstrap = load_json(args.bootstrap_file, {})
    if not isinstance(bootstrap.get("config"), dict):
        parser.error("bootstrap file has no config object")
    if not isinstance(bootstrap.get("bootstrap_user"), dict):
        parser.error("bootstrap file has no bootstrap_user object")
    required_config = (
        "region",
        "compartment_id",
        "cluster_name",
        "cluster_scope_id",
        "deployment_id",
    )
    required_user = ("username", "email", "topic_id", "subscription_id")
    if any(not bootstrap["config"].get(key) for key in required_config):
        parser.error("bootstrap config is incomplete")
    if any(not bootstrap["bootstrap_user"].get(key) for key in required_user):
        parser.error("bootstrap user is incomplete")

    merge_registry(args.registry, bootstrap)


if __name__ == "__main__":
    main()
