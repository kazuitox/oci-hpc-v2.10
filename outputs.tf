output "controller_public_ip" {
  value = oci_core_instance.controller.public_ip
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

output "ood_url" {
  value = tobool(var.use_ood) ? format("https://%s", local.host) : "NA"
}

output "ood_password" {
  value = tobool(var.use_ood) ? nonsensitive(random_password.ood_opc_password.result) : "NA"
}

output "ood_username" {
  value = tobool(var.use_ood) ? "${local.controller_username}@example.local" : "NA"
}
