resource "oci_core_image" "compute_node_custom_image" {
  count = var.import_compute_image_from_object_storage && !var.use_marketplace_image ? 1 : 0

  compartment_id = var.targetCompartment
  display_name   = var.compute_image_display_name

  image_source_details {
    source_type              = "objectStorageUri"
    source_uri               = var.compute_image_source_uri
    operating_system         = var.compute_image_operating_system
    operating_system_version = var.compute_image_operating_system_version
  }
}
