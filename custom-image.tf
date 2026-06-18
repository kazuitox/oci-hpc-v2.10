resource "oci_core_image" "compute_node_custom_image" {
  count = local.effective_import_compute_image && !local.effective_use_marketplace_image ? 1 : 0

  compartment_id = var.targetCompartment
  display_name   = local.compute_image_display_name

  image_source_details {
    source_type              = "objectStorageUri"
    source_uri               = local.compute_image_source_uri
    operating_system         = local.compute_image_operating_system
    operating_system_version = local.compute_image_operating_system_version
  }
}

resource "oci_core_image" "ood_vnc_gpu_custom_image" {
  count = var.ood_vnc_use_gpu && tobool(var.use_ood) ? 1 : 0

  compartment_id = var.targetCompartment
  display_name   = var.ood_vnc_gpu_image_display_name

  image_source_details {
    source_type              = "objectStorageUri"
    source_uri               = var.ood_vnc_gpu_image_source_uri
    operating_system         = var.ood_vnc_gpu_image_operating_system
    operating_system_version = var.ood_vnc_gpu_image_operating_system_version
  }
}
