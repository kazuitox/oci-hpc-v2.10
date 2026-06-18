variable "region" {}
variable "tenancy_ocid" {}
variable "targetCompartment" {}
variable "create_iam_policy_dynamic_group" {
  type    = bool
  default = true
}
variable "ad" {}
variable "secondary_ad" { default = "" }
variable "third_ad" { default = "" }
variable "use_multiple_ads" { default = false }
variable "ssh_key" { }
variable "cluster_network" { default = false }
variable "compute_cluster" { default = false }
variable "compute_cluster_exists" { default = false }
variable "compute_cluster_id" { default = "" }
variable "compute_cluster_start_index" { default = 0 }
variable "use_custom_name" { default = false }
variable "cluster_name" { default = "" }
variable "controller_ad" { default = "" }
variable "controller_shape" { default = "VM.Standard.E6.Flex" }
variable "controller_object_storage_par" { default = false }
variable "custom_controller_image" {
  type = string
  default = "image.ocid"
}
variable "custom_login_image" {
  type = string
  default = "image.ocid"
}
variable "controller_boot_volume_size" {default = 100}
variable "controller_boot_volume_backup" {default = false}
variable "controller_boot_volume_backup_type" {default = "INCREMENTAL"}
variable "controller_boot_volume_backup_period" {default = "ONE_DAY"}
variable "controller_boot_volume_backup_retention_seconds" {default = "7776000"}
variable "controller_boot_volume_backup_time_zone" {default = "REGIONAL_DATA_CENTER_TIME"}
variable "cluster_network_shape" { default = "BM.Optimized3.36" }
variable "instance_pool_shape" { default = "VM.Standard.E6.Flex" }
variable "node_count" { default = 0 }
variable "boot_volume_size" { default = 100 }
variable "use_marketplace_image" { default = false }
variable "image" { default = "ocid1.image.oc1..aaaaaaaa5yxem7wzie34hi5km4qm2t754tsfxrjuefyjivebrxjad4jcj5oa" }
variable "image_ocid" { default = "ocid1.image.oc1..aaaaaaaa5yxem7wzie34hi5km4qm2t754tsfxrjuefyjivebrxjad4jcj5oa" }
variable "import_compute_image_from_object_storage" {
  type    = bool
  default = true
}
variable "compute_image_source_uri" {
  type    = string
  default = "https://objectstorage.ap-tokyo-1.oraclecloud.com/p/G--enG8jrQxJhPnNs_O-gUqiHS2tU4IQ6cXqSRotr6-bXFhkfX7KCarOb_8q9g9D/n/idqcucnenh88/b/kazuito-bucket/o/Oracle-Linux-8.10-2025.07.21-0-OCA-RHCK-OFED-24.10-3.2.5.0-2025.08.21-0_oci-hpc-v2.10-image-v1.1"
}
variable "compute_image_display_name" {
  type    = string
  default = "Oracle-Linux-8.10-2025.07.21-0-OCA-RHCK-OFED-24.10-3.2.5.0-2025.08.21-0_oci-hpc-v2.10-image-v1.1"
}
variable "compute_image_operating_system" {
  type    = string
  default = "Oracle Linux"
}
variable "compute_image_operating_system_version" {
  type    = string
  default = "8.10"
}
variable "cluster_os" {
  type    = string
  default = "Oracle Linux 8"

  validation {
    condition     = contains(["Oracle Linux 8", "OracleLinux8", "Ubuntu 24.04", "Ubuntu24.04"], var.cluster_os)
    error_message = "cluster_os must be Oracle Linux 8 or Ubuntu 24.04."
  }
}
variable "use_preinstalled_compute_image" {
  type    = bool
  default = true
}
variable "import_gpcpu_image_from_object_storage" {
  type    = bool
  default = false
}
variable "use_compute_agent" { default = true }
variable "unsupported_controller_image" { default = "" }
variable "unsupported_login_image" { default = "" }
variable "use_cluster_nfs" { default = true}
variable "use_scratch_nfs" { default = false }
variable "cluster_nfs_path" { default = "/nfs/cluster" }
variable "scratch_nfs_path" { default = "/nfs/scratch" }
variable "vcn_compartment" { default = ""}
variable "vcn_id" { default = ""}
variable "use_existing_vcn" { default = false}
variable "public_subnet_id" { default = ""}
variable "private_subnet_id" { default = ""}
variable "vcn_subnet" { default = "172.16.0.0/21" }
variable "public_subnet" { default = "172.16.0.0/24" }
variable "additional_subnet" { default = "172.16.1.0/24" }
variable "rdma_subnet" { default = "10.224.0.0/12" }
variable "private_subnet" { default = "172.16.4.0/22" }
variable "ssh_cidr" { default = "0.0.0.0/0" }
variable "ood_source_cidr" { default = "" }
variable "ood_vnc_use_gpu" {
  type    = bool
  default = false
}
variable "ood_vnc_gpu_image_source_uri" {
  type    = string
  default = "https://objectstorage.ap-tokyo-1.oraclecloud.com/p/_cGy_ZWuygSW2Y9pq3yGEBmduhqWvAKgTB54_euyd7Na_VHKidiUMZRBgstp8X18/n/idqcucnenh88/b/kazuito-bucket/o/Oracle-Linux-8.10-2025.07.21-0-OCA-RHCK-OFED-24.10-3.2.5.0-2025.08.21-0_oci-hpc-v2.10-vnc-a10-gpu-image-v1.0"
}
variable "ood_vnc_gpu_image_display_name" {
  type    = string
  default = "Oracle-Linux-8.10-2025.07.21-0-OCA-RHCK-OFED-24.10-3.2.5.0-2025.08.21-0_oci-hpc-v2.10-vnc-a10-gpu-image-v1.0"
}
variable "ood_vnc_gpu_image_operating_system" {
  type    = string
  default = "Oracle Linux"
}
variable "ood_vnc_gpu_image_operating_system_version" {
  type    = string
  default = "8.10"
}
variable "slurm" { default = true }
variable "slurm_ha" { default = false }
variable "login_node" { default = false }
variable "login_ad" {default = ""}
variable "login_shape" { default = "VM.Standard.E5.Flex" }
variable "login_boot_volume_size" {default = 50}
variable "slurm_nfs" { default = false }
variable "rack_aware" { default = false }
variable "ldap" { default = true }
variable "spack" { default = false }
variable "install_application" { default = false }
variable "install_openfoam" { default = false }
variable "application" { default = "OpenFOAM" }
variable "application_version" { default = "v2312" }
variable "openfoam_version" { default = "v2312" }
variable "install_paraview" { default = false }
variable "paraview_version" { default = "5.11.2" }
variable "controller_ocpus" { default = 4}
variable "controller_ocpus_denseIO_flex" { default = 8}
variable "instance_pool_ocpus" { default = 64}
variable "instance_pool_ocpus_denseIO_flex" { default = 8}
variable "instance_pool_memory" { default = 96 }
variable "instance_pool_custom_memory" { default = true }
variable "login_ocpus" { default = 2}
variable "login_ocpus_denseIO_flex" { default = 8}
variable "controller_memory" { default = 16 }
variable "controller_custom_memory" { default = true }
variable "login_memory" { default = 16 }
variable "login_custom_memory" { default = true }
variable "privilege_sudo" { default = true }
variable "privilege_group_name" { default = "privilege" }


variable "marketplace_listing" {
  default = "HPC_OL8"
}
variable "marketplace_version_id" {
  type = map(string)
  default = {
       "HPC_OL8" = "Oracle-Linux-8.10-2025.07.21-0-OCA-RHCK-OFED-24.10-3.2.5.0-2025.08.21-0"
       "HPC_OL7" = "OracleLinux-7-OCA-RHCK-OFED-23.10-2.1.3.1-2024.05.08-0"
       "GPU_OL8_NV550" = "OracleLinux-8-OCA-RHCK-OFED-23.10-2.1.3.1-GPU-550-CUDA-12.4-2024.05.08-0"
       "GPU_OL7_NV550" = "OracleLinux-7-OCA-RHCK-OFED-23.10-2.1.3.1-GPU-550-CUDA-12.4-2024.05.13-0"
       "GPU_OL8_NV535" = "OracleLinux-8-OCA-RHCK-OFED-23.10-2.1.3.1-GPU-535-CUDA-12.2-2024.05.08-0"
       "GPU_OL7_NV535" = "OracleLinux-7-OCA-RHCK-OFED-23.10-2.1.3.1-GPU-535-CUDA-12.2-2024.05.13-0"
  }
}

# To find the Appcatalog OCID, run
# oci compute pic listing list --display-name "Oracle Linux 7 - HPC Cluster Networking Image"

variable "marketplace_listing_id_HPC" {
    default = "ocid1.appcataloglisting.oc1..aaaaaaaahz2xiwfcsbebmqg7sp6lhdt6r2vsjro5jfukkl5cntlqvfhkbzaq"
}
variable "marketplace_listing_id_GPU" {
    default = "ocid1.appcataloglisting.oc1..aaaaaaaab2hkpxsglxfbzitiiqv6djxzj5q5soxotwdem2dd2kbifgk4p55q"
}
variable "controller_block_volume_performance" {
/*
  Allowed values
  "0.  Lower performance"
  "10. Balanced performance"
  "20. High Performance"
*/

default = "10. Balanced performance"

}

variable "controller_block" {
  default = false
}

variable "controller_block_volume_size" {
  default = 1000
}

variable "login_block_volume_performance" {
/*
  Allowed values
  "0.  Lower performance"
  "10. Balanced performance"
  "20. High Performance"
*/

default = "10. Balanced performance"

}

variable "login_block" {
  default = false
}

variable "login_block_volume_size" {
  default = 1000
}
variable "scratch_nfs_type_cluster" { default = "nvme"}
variable "scratch_nfs_type_pool" { default = "none" }
variable "cluster_block_volume_size" { default = "1000" }
variable "cluster_block_volume_performance" { default = "10. Balanced performance"}

variable "inst_prin" { default = true}
variable "api_user_key" { default = ""}
variable "api_fingerprint" { default = ""}
variable "api_user_ocid" { default = ""}
variable "home_nfs" { default = true }
variable "home_fss" { default = false }
variable "configure" { default = true }

variable "hyperthreading" { default = true }

variable "autoscaling" { default = true }
variable "latency_check" { default = true }
variable "add_nfs" { default = true}
variable "create_fss" { default = true }
variable "mount_target_count" {
  default = 1
  type = number
  }
variable "fss_compartment" {default = ""}
variable "fss_ad" {default = ""}
variable "nfs_target_path" { default = "/share"}
variable "nfs_source_IP" { default = ""}
variable "nfs_source_path" { default = "/share"}
variable "nfs_options" {default = ""}
variable "monitoring" { default = false }
variable "enroot" { default = false }
variable "pyxis" { default = false }
variable "pam" { default = false }
variable "sacct_limits" { default = false }

variable "unsupported" {
  type=bool
  default = false
}

variable "queue" {default = "compute"}
variable "unsupported_controller" {
  type=bool
  default = false
}
variable "use_marketplace_image_controller" {
  type=bool
  default = true
}
variable "unsupported_login" {
  type=bool
  default = false
}
variable "controller_username" {
  type = string
  default = "opc"
}

variable "compute_username" {
  type = string
  default = "opc"
}
variable "login_username" {
  type = string
  default = "opc"
}

variable "autoscaling_monitoring" {
  type= bool
  default = false
}

variable "autoscaling_mysql_service" {
  type= bool
  default = false
}

variable "monitoring_shape_name" {
  type = string
  default = "MySQL.VM.Standard.E3.1.16GB"
}

variable "admin_username" {
  type = string
  default = "admin"
}

variable "admin_password" {
  type = string
  default = "Monitor1234!"
}

variable scratch_nfs_mount { default = ""}
variable scratch_nfs_export {default = ""}
variable cluster_nfs_mount {default = ""}
variable cluster_nfs_export {default = ""}

variable "private_deployment" { default = false }

variable "localdisk" { default = true }
variable "log_vol" { default = false }
variable "redundancy" { default = true }

variable "use_marketplace_image_login" { default = true}

variable "marketplace_listing_login" {
  default = "HPC_OL8"
}
variable "marketplace_listing_controller" {
  default = "HPC_OL8"
}
variable "zone_name" {
  default = ""
}
variable "dns_entries" {
  default = true
}
variable "healthchecks" {
  default = true
}
variable "BIOS" {
  default = false
}
variable "IOMMU" {
  default = false
}
variable "SMT" {
  default = true
}
variable "virt_instr" {
  default = false
}
variable "access_ctrl" {
  default = false
}
variable "numa_nodes_per_socket" {
  default = "Default"
}
variable "percentage_of_cores_enabled" {
  default = "Default"
}
variable "timezone" { default = "Asia/Tokyo" }
variable "use_ood" { default = "true" }
variable "tags" { default = "user" }

variable "ui_mode" {
  type    = string
  default = "SIMPLE"

  validation {
    condition     = contains(["SIMPLE", "ADVANCED"], var.ui_mode)
    error_message = "ui_mode must be SIMPLE or ADVANCED."
  }
}
