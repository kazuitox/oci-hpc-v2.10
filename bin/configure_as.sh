#!/bin/bash
#
# Cluster init configuration script
#

#
# wait for cloud-init completion on the controller host
#

scripts=`realpath $0`
folder=`dirname $scripts`
execution=1
playbooks_path=$folder/../playbooks/
inventory_path=$folder/../autoscaling/clusters/$1

if ! python3 "$folder/resize.py" --cluster_name "$1" --inventory "$inventory_path/inventory" prepare_local_block_volume; then
  echo "Failed to prepare local Block Volume inventory for $1" >&2
  exit 1
fi


username=`cat $inventory_path/inventory | grep compute_username= | tail -n 1| awk -F "=" '{print $2}'`
if [ "$username" == "" ]
then
username=$USER
fi

if ! /opt/oci-hpc/bin/wait_for_hosts.sh "$inventory_path/hosts_$1" "$username"; then
  echo "SSH did not become ready on all autoscaling nodes" >&2
  exit 1
fi
#
# Ansible will take care of key exchange and learning the host fingerprints, but for the first time we need
# to disable host key checking. 
#

if [[ $execution -eq 1 ]] ; then
  ANSIBLE_HOST_KEY_CHECKING=False ansible all -m setup --tree /tmp/ansible > /dev/null 2>&1
  ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook $playbooks_path/new_nodes.yml -i $inventory_path/inventory
else

	cat <<- EOF > /tmp/motd
	At least one of the cluster nodes has been innacessible during installation. Please validate the hosts and re-run: 
    ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook $playbooks_path/new_nodes.yml -i $inventory_path/inventory
EOF
  exit 1
fi 
