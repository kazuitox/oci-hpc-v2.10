#!/bin/bash

#
# A little waiter function to make sure all the nodes are up before we start configure
#

echo "Waiting for SSH to come up" 

ssh_options="-i ~/.ssh/cluster.key -o StrictHostKeyChecking=no"
ssh_wait_timeout=300
ssh_connect_timeout=10
ssh_retry_interval=5

wait_for_host() {
  local host=$1
  local username=$2
  local deadline=$((SECONDS + ssh_wait_timeout))

  echo "validating connection to: ${host}"
  while (( SECONDS < deadline )); do
    if ssh ${ssh_options} -o ConnectTimeout=${ssh_connect_timeout} "${username}@${host}" uptime ; then
      echo "SSH is ready on: ${host}"
      return 0
    fi

    if (( SECONDS + ssh_retry_interval >= deadline )); then
      break
    fi

    echo "Still waiting for ${host}"
    sleep ${ssh_retry_interval}
  done

  echo "Timed out waiting for SSH on: ${host}" >&2
  return 1
}

pids=()
hosts=()

while IFS= read -r host || [[ -n "${host}" ]]; do
  [[ -z "${host}" ]] && continue
  wait_for_host "${host}" "$2" &
  pids+=("$!")
  hosts+=("${host}")
done < "$1"

failed_hosts=()
for index in "${!pids[@]}"; do
  if ! wait "${pids[$index]}"; then
    failed_hosts+=("${hosts[$index]}")
  fi
done

if (( ${#failed_hosts[@]} > 0 )); then
  echo "SSH did not become ready on: ${failed_hosts[*]}" >&2
  exit 1
fi
