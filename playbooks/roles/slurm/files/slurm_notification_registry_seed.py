#!/usr/bin/env python3
"""Merge Terraform-managed bootstrap data into the runtime notification registry."""

import argparse
import fcntl
import json
import os
import stat
import tempfile


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
        config.update(bootstrap["config"])
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
    required_config = ("region", "compartment_id", "cluster_name", "cluster_scope_id")
    required_user = ("username", "email", "topic_id", "subscription_id")
    if any(not bootstrap["config"].get(key) for key in required_config):
        parser.error("bootstrap config is incomplete")
    if any(not bootstrap["bootstrap_user"].get(key) for key in required_user):
        parser.error("bootstrap user is incomplete")

    merge_registry(args.registry, bootstrap)


if __name__ == "__main__":
    main()
