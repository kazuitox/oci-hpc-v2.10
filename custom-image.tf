locals {
  required_compute_node_custom_image_compatible_shapes = toset([
    "VM.Standard.E6.Ax.Flex",
    "VM.Standard4.Ax.Flex",
    "BM.Standard.E6.Ax.192",
  ])
  available_compute_node_custom_image_compatible_shapes = setintersection(
    local.required_compute_node_custom_image_compatible_shapes,
    toset(data.oci_core_shapes.available_shapes.shapes[*].name),
  )
}

resource "oci_core_image" "compute_node_custom_image" {
  count = local.use_imported_compute_image ? 1 : 0

  compartment_id = var.targetCompartment
  display_name   = local.compute_image_display_name

  image_source_details {
    source_type              = "objectStorageUri"
    source_uri               = local.compute_image_source_uri
    operating_system         = local.compute_image_operating_system
    operating_system_version = local.compute_image_operating_system_version
  }
}

resource "oci_core_shape_management" "compute_node_custom_image_compatible_shapes" {
  for_each = local.use_imported_compute_image ? local.available_compute_node_custom_image_compatible_shapes : toset([])

  compartment_id = var.targetCompartment
  image_id       = oci_core_image.compute_node_custom_image[0].id
  shape_name     = each.value
}

resource "oci_core_image" "compute_node_gpgpu_custom_image" {
  count = local.import_gpgpu_compute_image ? 1 : 0

  compartment_id = var.targetCompartment
  display_name   = local.simple_gpgpu_compute_image.display_name

  image_source_details {
    source_type              = "objectStorageUri"
    source_uri               = local.simple_gpgpu_compute_image.source_uri
    operating_system         = local.simple_gpgpu_compute_image.operating_system
    operating_system_version = local.simple_gpgpu_compute_image.operating_system_version
  }
}

resource "oci_core_image" "ood_vnc_gpu_custom_image" {
  count = local.ood_desktop_gpu_enabled ? 1 : 0

  compartment_id = var.targetCompartment
  display_name   = var.ood_vnc_gpu_image_display_name

  image_source_details {
    source_type              = "objectStorageUri"
    source_uri               = var.ood_vnc_gpu_image_source_uri
    operating_system         = var.ood_vnc_gpu_image_operating_system
    operating_system_version = var.ood_vnc_gpu_image_operating_system_version
  }
}
