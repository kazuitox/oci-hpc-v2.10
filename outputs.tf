output "controller" {
  value = local.host
}

output "private_ips" {
  value = join(" ", local.cluster_instances_ips)
}

output "backup" {
  value = var.slurm_ha ? local.host_backup : "No Slurm Backup Defined"
}

output "login" {
  value = var.login_node ? local.host_login : "No Login Node Defined"
}

output "ood_opc_password" {
  value = nonsensitive(random_password.ood_opc_password.result)
}

output "ood_opc_username" {
  value = "opc@example.local"
}
