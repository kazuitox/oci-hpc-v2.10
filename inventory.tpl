[controller]
${controller_name} ansible_host=${controller_ip} ansible_user=${controller_username} role=controller ansible_python_interpreter=/usr/bin/python
[slurm_backup]
%{ if backup_name != "" }${backup_name} ansible_host=${backup_ip} ansible_user=${compute_username} role=controller%{ endif }
[login]
%{ if login_name != "" }${login_name} ansible_host=${login_ip} ansible_user=${compute_username} role=login%{ endif }
[compute_to_add]
[compute_configured]
%{ for host, ip in compute ~}
${host} ansible_host=${ip} ansible_user=${compute_username} role=compute
%{ endfor ~}
[compute_to_destroy]
[nfs]
%{ if nfs != "" }${nfs} ansible_user=${compute_username} role=nfs%{ endif }
[compute:children]
compute_to_add
compute_configured
[all:vars]
ansible_connection=ssh
rdma_network=${rdma_network}
rdma_netmask=${rdma_netmask}
public_subnet=${public_subnet} 
private_subnet=${private_subnet}
nvme_path=/mnt/localdisk/
scratch_nfs = ${scratch_nfs}
home_nfs = ${home_nfs} 
create_fss = ${create_fss} 
home_fss = ${home_fss} 
cluster_nfs = ${cluster_nfs}
cluster_nfs_path = ${cluster_nfs_path}
slurm_nfs_path = ${slurm_nfs_path}
scratch_nfs_path = ${scratch_nfs_path}
cluster_network = ${cluster_network}
slurm = ${slurm}
rack_aware = ${rack_aware}
spack = ${spack} 
controller_block = ${controller_block} 
login_block = ${login_block}
scratch_nfs_type = ${scratch_nfs_type}
controller_mount_ip = ${controller_mount_ip}
login_mount_ip = ${login_mount_ip}
cluster_mount_ip = ${cluster_mount_ip}
autoscaling = ${autoscaling}
cluster_name = ${cluster_name}
shape=${shape}
add_nfs=${add_nfs}
nfs_target_path=${nfs_target_path}
nfs_source_IP=${nfs_source_IP}
nfs_source_path=${nfs_source_path}
nfs_options=${nfs_options}
localdisk=${localdisk}
redundancy=${redundancy}
log_vol=${log_vol}
instance_pool_ocpus=${instance_pool_ocpus}
queue=${queue}
monitoring=${monitoring}
hyperthreading=${hyperthreading}
ldap=${ldap}
autoscaling_monitoring=${autoscaling_monitoring}
autoscaling_mysql_service=${autoscaling_mysql_service}
monitoring_mysql_ip=${monitoring_mysql_ip}
admin_password = ${admin_password}
admin_username = ${admin_username}
instance_type=permanent
enroot=${enroot}
pyxis=${pyxis}
pam=${pam}
privilege_sudo=${privilege_sudo}
privilege_group_name=${privilege_group_name}
latency_check=${latency_check}
compute_username=${compute_username}
controller_username=${controller_username}
region= ${region}
tenancy_ocid = ${tenancy_ocid}
inst_prin = ${inst_prin}
api_fingerprint = ${api_fingerprint}
api_user_ocid = ${api_user_ocid}
sacct_limits=${sacct_limits}
use_compute_agent=${use_compute_agent}
zone_name=${zone_name}
dns_entries=${dns_entries}
healthchecks=${healthchecks}
timezone=${timezone}
