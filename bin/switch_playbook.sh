i#!/usr/bin/env bash
# ------------------------------------------------------------
# Switch playbook variant: normal <-> lite  (absolute paths)
# Usage: ./switch_playbook.sh lite    # to lite
#        ./switch_playbook.sh normal  # to normal
# ------------------------------------------------------------
set -euo pipefail

usage() {
  echo "Usage: $0 [lite|normal]" >&2
  exit 1
}

[[ $# -eq 1 ]] || usage
mode="$1"
[[ "$mode" == "lite" || "$mode" == "normal" ]] || usage

BASE_DIR="/opt/oci-hpc/playbooks"

# normal_file:lite_file pairs (absolute paths)
declare -a PAIRS=(
  "${BASE_DIR}/roles/nfs-server/tasks/el.yml:${BASE_DIR}/roles/nfs-server/tasks/lite_el.yml"
  "${BASE_DIR}/roles/nfs-client/tasks/el.yml:${BASE_DIR}/roles/nfs-client/tasks/lite_el.yml"
  "${BASE_DIR}/roles/sssd/tasks/el-8.yml:${BASE_DIR}/roles/sssd/tasks/lite_el-8.yml"
  "${BASE_DIR}/roles/slurm/tasks/compute.yml:${BASE_DIR}/roles/slurm/tasks/lite_compute.yml"
  "${BASE_DIR}/roles/slurm/tasks/common_pmix.yml:${BASE_DIR}/roles/slurm/tasks/lite_common_pmix.yml"
  "${BASE_DIR}/roles/slurm/tasks/common.yml:${BASE_DIR}/roles/slurm/tasks/lite_common.yml"
  "${BASE_DIR}/new_nodes.yml:${BASE_DIR}/lite_new_nodes.yml"
)

for pair in "${PAIRS[@]}"; do
  IFS=":" read -r normal lite <<<"$pair"

  if [[ "$mode" == "lite" ]]; then
    # keep backup only the first time
    [[ -f "${normal}.normal" ]] || cp "$normal" "${normal}.normal"
    cp "$lite" "$normal"
    echo "✔ Replaced: $normal -> lite version"
  else
    if [[ -f "${normal}.normal" ]]; then
      mv "${normal}.normal" "$normal"
      echo "✔ Restored: $normal -> normal version"
    else
      echo "⚠ No backup found, skip: $normal"
    fi
  fi
done
