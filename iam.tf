resource "oci_identity_policy" "compute_management_autoscaling_policy" {
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "Compute-Management-Autoscaling-Policy"
  description    = "Allows the Compute Management service to manage resources required for HPC autoscaling."

  statements = [
    "allow service compute_management to use tag-namespace in tenancy",
    "allow service compute_management to manage compute-management-family in tenancy",
    "allow service compute_management to read app-catalog-listing in tenancy",
  ]
}

resource "oci_identity_dynamic_group" "autoscaling_dg" {
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "autoscaling_dg"
  description    = "Dynamic group for instances in the HPC autoscaling target compartment."
  matching_rule  = "Any {instance.compartment.id = '${var.targetCompartment}'}"
}

resource "oci_identity_policy" "autoscaling_policy" {
  provider       = oci.home
  compartment_id = var.tenancy_ocid
  name           = "Autoscaling-Policy"
  description    = "Allows HPC autoscaling instances to manage resources in the tenancy."

  statements = [
    "allow dynamic-group ${oci_identity_dynamic_group.autoscaling_dg.name} to read app-catalog-listing in tenancy",
    "allow dynamic-group ${oci_identity_dynamic_group.autoscaling_dg.name} to use tag-namespace in tenancy",
    "allow dynamic-group ${oci_identity_dynamic_group.autoscaling_dg.name} to manage all-resources in tenancy",
  ]
}
