resource "oci_core_volume" "controller_volume" { 
  count = var.controller_block ? 1 : 0
  availability_domain = var.controller_ad
  compartment_id = var.targetCompartment
  display_name = "${local.cluster_name}-controller-volume"
  
  size_in_gbs = var.controller_block_volume_size
  vpus_per_gb = split(".", var.controller_block_volume_performance)[0]
} 

resource "oci_core_volume_attachment" "controller_volume_attachment" { 
  count = var.controller_block ? 1 : 0 
  attachment_type = "iscsi"
  volume_id       = oci_core_volume.controller_volume[0].id
  instance_id     = oci_core_instance.controller.id
  display_name    = "${local.cluster_name}-controller-volume-attachment"
  device          = "/dev/oracleoci/oraclevdb"
  is_shareable    = true
} 

resource "oci_core_volume_backup_policy" "controller_boot_volume_backup_policy" {
  count = var.controller_boot_volume_backup ? 1 : 0
	compartment_id = var.targetCompartment
	display_name = "${local.cluster_name}-controller_boot_volume_daily"
	schedules {
		backup_type = var.controller_boot_volume_backup_type
		period = var.controller_boot_volume_backup_period
		retention_seconds = var.controller_boot_volume_backup_retention_seconds
		time_zone = var.controller_boot_volume_backup_time_zone
	}
}

resource "oci_core_volume_backup_policy_assignment" "boot_volume_backup_policy" {
  count = var.controller_boot_volume_backup ? 1 : 0
  depends_on = [oci_core_volume_backup_policy.controller_boot_volume_backup_policy]
  asset_id  = oci_core_instance.controller.boot_volume_id
  policy_id = oci_core_volume_backup_policy.controller_boot_volume_backup_policy[0].id
}

resource "oci_resourcemanager_private_endpoint" "rms_private_endpoint" {
  count = var.private_deployment ? 1 : 0
  compartment_id = var.targetCompartment
  display_name   = "rms_private_endpoint"
  description    = "rms_private_endpoint_description"
  vcn_id         = local.vcn_id
  subnet_id      = local.subnet_id
}

resource "null_resource" "boot_volume_backup_policy" { 
  depends_on = [oci_core_instance.controller, oci_core_volume_backup_policy.controller_boot_volume_backup_policy, oci_core_volume_backup_policy_assignment.boot_volume_backup_policy] 
  triggers = { 
    controller = oci_core_instance.controller.id
  } 
}

resource "oci_core_instance" "controller" {
  depends_on          = [local.controller_subnet]
  availability_domain = var.controller_ad
  compartment_id      = var.targetCompartment
  shape               = var.controller_shape

  dynamic "shape_config" {
    for_each = local.is_controller_flex_shape
      content {
        ocpus = shape_config.value
        memory_in_gbs = var.controller_custom_memory ? var.controller_memory : 16 * shape_config.value
      }
  }
  agent_config {
    is_management_disabled = true
    }
  display_name        = "${local.cluster_name}-controller"

  freeform_tags = {
    "cluster_name" = local.cluster_name
    "parent_cluster" = local.cluster_name
  }

  metadata = {
    ssh_authorized_keys = "${var.ssh_key}\n${tls_private_key.ssh.public_key_openssh}"
    user_data           = base64encode(data.template_file.controller_config.rendered)
  }
  source_details {
//    source_id   = var.use_standard_image ? data.oci_core_images.linux.images.0.id : local.custom_controller_image_ocid
    source_id = local.controller_image
    boot_volume_size_in_gbs = var.controller_boot_volume_size
    source_type = "image"
  }

  create_vnic_details {
    subnet_id = local.controller_subnet_id
    assign_public_ip = local.controller_bool_ip
  }
} 

resource "null_resource" "controller" { 
  depends_on = [oci_core_instance.controller, oci_core_volume_attachment.controller_volume_attachment ] 
  triggers = { 
    controller = oci_core_instance.controller.id
  } 

  provisioner "remote-exec" {
    inline = [
      "#!/bin/bash",
      "sudo mkdir -p /opt/oci-hpc",      
      "sudo chown ${var.controller_username}:${var.controller_username} /opt/oci-hpc/",
      "mkdir -p /opt/oci-hpc/bin",
      "mkdir -p /opt/oci-hpc/playbooks"
      ]
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
  provisioner "file" {
    source        = "playbooks"
    destination   = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "file" {
    source      = "autoscaling"
    destination = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "file" {
    source      = "bin"
    destination = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "file" {
    source      = "conf"
    destination = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
    provisioner "file" {
    source      = "logs"
    destination = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
  provisioner "file" {
    source      = "samples"
    destination = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
  provisioner "file" {
    source      = "scripts"
    destination = "/opt/oci-hpc/"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
  provisioner "file" { 
    content        = templatefile("${path.module}/configure.tpl", { 
      configure = var.configure
    })
    destination   = "/tmp/configure.conf"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "file" {
    content     = tls_private_key.ssh.private_key_openssh
    destination = "/home/${var.controller_username}/.ssh/cluster.key"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

    provisioner "file" {
    content     = tls_private_key.ssh.public_key_openssh
    destination = "/home/${var.controller_username}/.ssh/id_rsa.pub"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
}
resource "null_resource" "cluster" { 
  depends_on = [null_resource.controller, null_resource.backup, oci_core_compute_cluster.compute_cluster, oci_core_cluster_network.cluster_network, oci_core_instance.controller, oci_core_volume_attachment.controller_volume_attachment ] 
  triggers = { 
    cluster_instances = join(", ", local.cluster_instances_names)
  } 

  provisioner "file" {
    content        = templatefile("${path.module}/inventory.tpl", {  
      controller_name = oci_core_instance.controller.display_name, 
      controller_ip = oci_core_instance.controller.private_ip,
      backup_name = var.slurm_ha ? oci_core_instance.backup[0].display_name : "",
      backup_ip = var.slurm_ha ? oci_core_instance.backup[0].private_ip: "",
      login_name = var.login_node ? oci_core_instance.login[0].display_name : "",
      login_ip = var.login_node ? oci_core_instance.login[0].private_ip: "",
      compute = var.node_count > 0 ? zipmap(local.cluster_instances_names, local.cluster_instances_ips) : zipmap([],[])
      public_subnet = data.oci_core_subnet.public_subnet.cidr_block, 
      private_subnet = data.oci_core_subnet.private_subnet.cidr_block, 
      rdma_network = cidrhost(var.rdma_subnet, 0),
      rdma_netmask = cidrnetmask(var.rdma_subnet),
      zone_name = local.zone_name,
      dns_entries = var.dns_entries,
      nfs = var.node_count > 0 && var.use_scratch_nfs ? local.cluster_instances_names[0] : "",
      home_nfs = var.home_nfs,
      create_fss = var.create_fss,
      home_fss = var.home_fss,
      scratch_nfs = var.use_scratch_nfs && var.node_count > 0,
      cluster_nfs = var.use_cluster_nfs,
      cluster_nfs_path = var.cluster_nfs_path,
      scratch_nfs_path = var.scratch_nfs_path,
      add_nfs = var.add_nfs,
      nfs_target_path = var.nfs_target_path,
      nfs_source_IP = local.nfs_source_IP,
      nfs_source_path = var.nfs_source_path,
      nfs_options = var.nfs_options,
      localdisk = var.localdisk,
      log_vol = var.log_vol,
      redundancy = var.redundancy,
      cluster_network = var.cluster_network,
      use_compute_agent = var.use_compute_agent,
      slurm = var.slurm,
      rack_aware = var.rack_aware,
      slurm_nfs_path = var.slurm_nfs ? var.nfs_source_path : var.cluster_nfs_path
      spack = var.spack,
      ldap = var.ldap,
      timezone = var.timezone,
      controller_block = var.controller_block, 
      login_block = var.login_block, 
      scratch_nfs_type = local.scratch_nfs_type,
      controller_mount_ip = local.controller_mount_ip,
      login_mount_ip = local.login_mount_ip,
      cluster_mount_ip = local.mount_ip,
      autoscaling = var.autoscaling,
      cluster_name = local.cluster_name,
      shape = local.shape,
      instance_pool_ocpus = local.instance_pool_ocpus,
      queue=var.queue,
      monitoring = var.monitoring,
      hyperthreading = var.hyperthreading,
      controller_username = var.controller_username,
      compute_username = var.compute_username,
      autoscaling_monitoring = var.autoscaling_monitoring,
      autoscaling_mysql_service = var.autoscaling_mysql_service,
      monitoring_mysql_ip = var.autoscaling_monitoring && var.autoscaling_mysql_service ? oci_mysql_mysql_db_system.monitoring_mysql_db_system[0].ip_address : "localhost",
      admin_password = var.admin_password,
      admin_username = var.autoscaling_mysql_service ? var.admin_username : "root",
      enroot = var.enroot,
      pyxis = var.pyxis,
      privilege_sudo = var.privilege_sudo,
      privilege_group_name = var.privilege_group_name,
      latency_check = var.latency_check,
      pam = var.pam,
      sacct_limits = var.sacct_limits,
      inst_prin = var.inst_prin,
      region = var.region,
      tenancy_ocid = var.tenancy_ocid,
      api_fingerprint = var.api_fingerprint,
      api_user_ocid = var.api_user_ocid,
      healthchecks = var.healthchecks
      })

    destination   = "/opt/oci-hpc/playbooks/inventory"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }


  provisioner "file" {
    content     = var.node_count > 0 ? join("\n",local.cluster_instances_ips) : "\n"
    destination = "/tmp/hosts"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "file" {
    content        = templatefile(var.inst_prin ? "${path.module}/autoscaling/provider_inst_prin.tpl" : "${path.module}/autoscaling/provider_user.tpl", {  
      api_user_ocid = var.api_user_ocid, 
      api_fingerprint = var.api_fingerprint,
      private_key_path = "/opt/oci-hpc/autoscaling/credentials/key.pem",
      tenancy_ocid = var.tenancy_ocid
      })

    destination   = "/opt/oci-hpc/autoscaling/tf_init/provider.tf"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "file" {
    content        = templatefile("${path.module}/queues.conf", {  
      cluster_network = var.cluster_network,
      use_compute_agent = var.use_compute_agent,
      compute_cluster = var.compute_cluster,
      marketplace_listing = var.marketplace_listing,
      image = local.image_ocid,
      use_marketplace_image = var.use_marketplace_image,
      boot_volume_size = var.boot_volume_size,
      shape = var.cluster_network ? var.cluster_network_shape : var.instance_pool_shape,
      region = var.region,
      ad = var.use_multiple_ads? join(" ", [var.ad, var.secondary_ad, var.third_ad]) : var.ad,
      private_subnet = data.oci_core_subnet.private_subnet.cidr_block,
      private_subnet_id = local.subnet_id,
      targetCompartment = var.targetCompartment,
      instance_pool_ocpus = local.instance_pool_ocpus,
      instance_pool_memory = var.instance_pool_memory,
      instance_pool_custom_memory = var.instance_pool_custom_memory,
      queue=var.queue,
      hyperthreading = var.hyperthreading
      })

    destination   = "/opt/oci-hpc/conf/queues.conf"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
  
  provisioner "file" {
    content        = templatefile("${path.module}/conf/variables.tpl", {  
      controller_name = oci_core_instance.controller.display_name, 
      controller_ip = oci_core_instance.controller.private_ip, 
      backup_name = var.slurm_ha ? oci_core_instance.backup[0].display_name : "",
      backup_ip = var.slurm_ha ? oci_core_instance.backup[0].private_ip: "",
      login_name = var.login_node ? oci_core_instance.login[0].display_name : "",
      login_ip = var.login_node ? oci_core_instance.login[0].private_ip: "",
      compute = var.node_count > 0 ? zipmap(local.cluster_instances_names, local.cluster_instances_ips) : zipmap([],[])
      public_subnet = data.oci_core_subnet.public_subnet.cidr_block,
      public_subnet_id = local.controller_subnet_id,
      private_subnet = data.oci_core_subnet.private_subnet.cidr_block,
      private_subnet_id = local.subnet_id,
      rdma_subnet = var.rdma_subnet,
      nfs = var.node_count > 0 ? local.cluster_instances_names[0] : "",
      scratch_nfs = var.use_scratch_nfs && var.node_count > 0,
      scratch_nfs_path = var.scratch_nfs_path,
      use_scratch_nfs = var.use_scratch_nfs,
      slurm = var.slurm,
      rack_aware = var.rack_aware,
      slurm_nfs_path = var.add_nfs ? var.nfs_source_path : var.cluster_nfs_path
      spack = var.spack,
      ldap = var.ldap,
      timezone = var.timezone,
      controller_block = var.controller_block, 
      login_block = var.login_block, 
      scratch_nfs_type = local.scratch_nfs_type,
      controller_mount_ip = local.controller_mount_ip,
      login_mount_ip = local.login_mount_ip,
      cluster_mount_ip = local.mount_ip,
      scratch_nfs_type_cluster = var.scratch_nfs_type_cluster,
      scratch_nfs_type_pool = var.scratch_nfs_type_pool,
      controller_block_volume_performance = var.controller_block_volume_performance,
      region = var.region,
      tenancy_ocid = var.tenancy_ocid,
      vcn_subnet = var.vcn_subnet,
      vcn_id = local.vcn_id,
      zone_name = local.zone_name,
      dns_entries = var.dns_entries,
      cluster_block_volume_size = var.cluster_block_volume_size,
      cluster_block_volume_performance = var.cluster_block_volume_performance,
      ssh_cidr = var.ssh_cidr,
      use_cluster_nfs = var.use_cluster_nfs,
      cluster_nfs_path = var.cluster_nfs_path,
      home_nfs = var.home_nfs,
      create_fss = var.create_fss,
      home_fss = var.home_fss,
      add_nfs = var.add_nfs,
      nfs_target_path = var.nfs_target_path,
      nfs_source_IP = local.nfs_source_IP,
      nfs_source_path = var.nfs_source_path,
      nfs_options = var.nfs_options,
      localdisk = var.localdisk,
      log_vol = var.log_vol,
      redundancy = var.redundancy,
      monitoring = var.monitoring,
      hyperthreading = var.hyperthreading,
      unsupported = var.unsupported,
      autoscaling_monitoring = var.autoscaling_monitoring,
      enroot = var.enroot,
      pyxis = var.pyxis,
      privilege_sudo = var.privilege_sudo,
      privilege_group_name = var.privilege_group_name,
      latency_check = var.latency_check,
      private_deployment = var.private_deployment,
      use_multiple_ads = var.use_multiple_ads,
      controller_username = var.controller_username,
      compute_username = var.compute_username,
      pam = var.pam,
      sacct_limits = var.sacct_limits, 
      use_compute_agent = var.use_compute_agent,
      BIOS = var.BIOS,
      IOMMU = var.IOMMU,
      SMT = var.SMT,
      virt_instr = var.virt_instr,
      access_ctrl = var.access_ctrl,
      numa_nodes_per_socket = var.numa_nodes_per_socket,
      percentage_of_cores_enabled = var.percentage_of_cores_enabled,
      healthchecks = var.healthchecks
      })

    destination   = "/opt/oci-hpc/conf/variables.tf"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

provisioner "file" {
    content        = templatefile("${path.module}/initial_mon.tpl", {  
      cluster_ocid=local.cluster_ocid,
      shape = var.cluster_network ? var.cluster_network_shape : var.instance_pool_shape,
      queue=var.queue,
      cluster_network = var.cluster_network,
      ocids = join(",", local.cluster_instances_ids),
      hostnames = join(",", local.cluster_instances_names),
      ips = join(",", local.cluster_instances_ips)
      })

    destination   = "/tmp/initial.mon"
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
  provisioner "file" {
    content     = base64decode(var.api_user_key)
    destination   = "/opt/oci-hpc/autoscaling/credentials/key.pem" 
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }

  provisioner "remote-exec" {
    inline = [
      "#!/bin/bash",
      "chmod 600 /home/${var.controller_username}/.ssh/cluster.key",
      "cp /home/${var.controller_username}/.ssh/cluster.key /home/${var.controller_username}/.ssh/id_rsa",
      "chmod a+x /opt/oci-hpc/bin/*.sh",
      "timeout --foreground 60m /opt/oci-hpc/bin/controller.sh",
      "chmod 755 /opt/oci-hpc/autoscaling/crontab/*.sh",
      "chmod 755 /opt/oci-hpc/samples/*.sh",
      "chmod 600 /opt/oci-hpc/autoscaling/credentials/key.pem",
      "echo ${var.configure} > /tmp/configure.conf",
      "timeout 2h /opt/oci-hpc/bin/configure.sh | tee /opt/oci-hpc/logs/initial_configure.log",
      "exit_code=$${PIPESTATUS[0]}",
      "/opt/oci-hpc/bin/initial_monitoring.sh",
      "exit $exit_code"     ]
    connection {
      host        = local.host
      type        = "ssh"
      user        = var.controller_username
      private_key = tls_private_key.ssh.private_key_pem
    }
  }
}

data "oci_objectstorage_namespace" "compartment_namespace" {
    compartment_id = var.targetCompartment
}

locals {
  current_timestamp           = timestamp()
  current_timestamp_formatted = formatdate("YYYYMMDDhhmmss", local.current_timestamp)
  rdma_nic_metric_bucket_name = format("%s_%s","RDMA_NIC_metrics",local.current_timestamp_formatted)
  par_path = ".."
}
/*
saving the PAR into file: ../PAR_file_for_metrics.
this PAR is used by the scripts to upload NIC metrics to object storage (i.e. script: upload_rdma_nic_metrics.sh)
*/


resource "oci_objectstorage_bucket" "RDMA_NIC_metrics_bucket" {
  count = (var.controller_object_storage_par) ? 1 : 0
  compartment_id = var.targetCompartment
  name           = local.rdma_nic_metric_bucket_name
  namespace      = data.oci_objectstorage_namespace.compartment_namespace.namespace
  versioning     = "Enabled"
}

resource "oci_objectstorage_preauthrequest" "RDMA_NIC_metrics_par" {
  count = (var.controller_object_storage_par) ? 1 : 0
  depends_on  = [oci_objectstorage_bucket.RDMA_NIC_metrics_bucket]
  access_type = "AnyObjectWrite"
  bucket      = local.rdma_nic_metric_bucket_name
  name         = format("%s-%s", "RDMA_NIC_metrics_bucket", var.tenancy_ocid)
  namespace    = data.oci_objectstorage_namespace.compartment_namespace.namespace
  time_expires = "2030-08-01T00:00:00+00:00"
}


output "RDMA_NIC_metrics_url" {
 depends_on = [oci_objectstorage_preauthrequest.RDMA_NIC_metrics_par]
 value = (var.controller_object_storage_par) ? "https://objectstorage.${var.region}.oraclecloud.com${oci_objectstorage_preauthrequest.RDMA_NIC_metrics_par[0].access_uri}" : ""
}


resource "local_file" "PAR" {
    count = (var.controller_object_storage_par) ? 1 : 0
    depends_on = [oci_objectstorage_preauthrequest.RDMA_NIC_metrics_par]
    content     = "https://objectstorage.${var.region}.oraclecloud.com${oci_objectstorage_preauthrequest.RDMA_NIC_metrics_par[0].access_uri}"
    filename = "${local.par_path}/PAR_file_for_metrics"
  }


resource "oci_dns_rrset" "rrset-controller" {
  count = var.dns_entries ? 1 : 0
  zone_name_or_id = data.oci_dns_zones.dns_zones.zones[0].id
  domain          = "${oci_core_instance.controller.display_name}.${local.zone_name}"
  rtype           = "A"
  items {
    domain = "${oci_core_instance.controller.display_name}.${local.zone_name}"
    rtype  = "A"
    rdata  = oci_core_instance.controller.private_ip
    ttl    = 3600
  }
  scope = "PRIVATE"
  view_id = data.oci_dns_views.dns_views.views[0].id
}

#oci dns record rrset update --zone-name-or-id ocid1.dns-zone.oc1.ca-toronto-1.aaaaaaaadwpfuij3w7jpg3sj6gzc5ete2yeknrmjgwzvs6qytgkqad2vhbmq --domain mint-ocelot-controller.mint-ocelot.local --rtype A --auth instance_principal --scope PRIVATE --view-id  ocid1.dnsview.oc1.ca-toronto-1.aaaaaaaamhhzrbwe4f3rx5i2hx2xlnubfjc37uvy3e7bjrbyaln5o7zjfvpa --items '[{ "rdata":"1.1.1.1","ttl":300,"domain":"mint-ocelot-controller.mint-ocelot.local","rtype":"A"}]' --force
