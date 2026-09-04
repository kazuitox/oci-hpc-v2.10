resource "oci_identity_dynamic_group" "slurm_notification_controllers" {
  count          = var.slurm_job_notifications_enabled ? 1 : 0
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "slurm_notification_controllers_${local.slurm_notification_identity_suffix}"
  description    = "Controllers allowed to manage Slurm job notifications for ${local.cluster_name}."
  matching_rule  = local.slurm_notification_controller_matching_rule

  freeform_tags = {
    "cluster_name"       = local.cluster_name
    "parent_cluster"     = local.cluster_name
    "notification_scope" = local.slurm_notification_cluster_scope
    "managed_by"         = "terraform"
  }
}

resource "oci_identity_policy" "slurm_notification_controllers" {
  count          = var.slurm_job_notifications_enabled ? 1 : 0
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "slurm-notification-controllers-${local.slurm_notification_identity_suffix}"
  description    = "Allows the ${local.cluster_name} controllers to manage Slurm notification topics and subscriptions."

  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.slurm_notification_controllers[0].name} to manage ons-topics in compartment id ${var.targetCompartment}",
  ]

  freeform_tags = {
    "cluster_name"       = local.cluster_name
    "parent_cluster"     = local.cluster_name
    "notification_scope" = local.slurm_notification_cluster_scope
    "managed_by"         = "terraform"
  }
}

resource "oci_ons_notification_topic" "slurm_local_user" {
  count          = var.slurm_job_notifications_enabled ? 1 : 0
  compartment_id = var.targetCompartment
  name           = "slurm-${local.slurm_notification_identity_suffix}-${local.slurm_notification_local_topic_suffix}"
  description    = "Slurm job notifications for ${local.controller_username} on ${local.cluster_name}."

  freeform_tags = {
    "cluster_name"       = local.cluster_name
    "parent_cluster"     = local.cluster_name
    "notification_scope" = local.slurm_notification_cluster_scope
    "slurm_user"         = local.controller_username
    "managed_by"         = "terraform"
  }
}

resource "oci_ons_subscription" "slurm_local_user_email" {
  count          = var.slurm_job_notifications_enabled ? 1 : 0
  compartment_id = var.targetCompartment
  topic_id       = oci_ons_notification_topic.slurm_local_user[0].id
  protocol       = "EMAIL"
  endpoint       = local.slurm_notification_admin_email

  freeform_tags = {
    "cluster_name"       = local.cluster_name
    "parent_cluster"     = local.cluster_name
    "notification_scope" = local.slurm_notification_cluster_scope
    "slurm_user"         = local.controller_username
    "managed_by"         = "terraform"
  }
}
