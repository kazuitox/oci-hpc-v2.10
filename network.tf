resource "oci_core_vcn" "vcn" {
  count          = var.use_existing_vcn ? 0 : 1
  cidr_block     = var.vcn_subnet
  compartment_id = var.targetCompartment
  display_name   = "${local.cluster_name}_VCN"
  dns_label      = "cluster"
}

resource "oci_core_security_list" "internal-security-list" {
  count          = var.use_existing_vcn ? 0 : 1
  vcn_id         = oci_core_vcn.vcn[0].id
  compartment_id = var.targetCompartment

  ingress_security_rules {
    protocol = "all"
    source   = var.vcn_subnet
  }
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  ingress_security_rules { 
    protocol = "1"
    source = "0.0.0.0/0"
    icmp_options { 
      type = "3"
      code = "4"
    }
  }

  ingress_security_rules { 
    protocol = "1"
    source = var.vcn_subnet
    icmp_options { 
      type = "3"
    }
  }
}

resource "oci_core_security_list" "public-security-list" {
  count          = (var.use_existing_vcn || var.private_deployment) ? 0 : 1
  vcn_id         = oci_core_vcn.vcn[0].id
  compartment_id = var.targetCompartment

  ingress_security_rules {
    protocol = "all"
    source   = var.vcn_subnet
  }

  ingress_security_rules {
    protocol = "6"
    source   = var.ssh_cidr
    tcp_options {
      max = "22"
      min = "22"
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = var.ssh_cidr
    tcp_options {
      max = "3000"
      min = "3000"
    }
  }
  ingress_security_rules { 
    protocol = "1"
    source = "0.0.0.0/0"
    icmp_options { 
      type = "3"
      code = "4"
    }
  }

  ingress_security_rules { 
    protocol = "1"
    source = var.vcn_subnet
    icmp_options { 
      type = "3"
    }
  }

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_internet_gateway" "ig1" {
  count          = (var.use_existing_vcn || var.private_deployment) ? 0 : 1
  vcn_id         = oci_core_vcn.vcn[0].id
  compartment_id = var.targetCompartment
  display_name   = "${local.cluster_name}_internet-gateway"
}

resource "oci_core_nat_gateway" "ng1" {
  count          = var.use_existing_vcn ? 0 : 1
  vcn_id         = oci_core_vcn.vcn[0].id
  compartment_id = var.targetCompartment
  display_name   = "${local.cluster_name}_nat-gateway"
}


resource "oci_core_service_gateway" "sg1" {
  count          = var.use_existing_vcn ? 0 : 1
  vcn_id         = oci_core_vcn.vcn[0].id
  compartment_id = var.targetCompartment
  display_name   = "${local.cluster_name}_service-gateway"

  services {
    service_id = data.oci_core_services.services.services[0]["id"]
  }
}

resource "oci_core_route_table" "public_route_table" {
  count          = (var.use_existing_vcn || var.private_deployment) ? 0 : 1
  compartment_id = var.targetCompartment
  vcn_id         = oci_core_vcn.vcn[0].id
  display_name   = "${local.cluster_name}_public_route_table"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.ig1[0].id
  }
}

resource "oci_core_route_table" "private_route_table" {
  count          = var.use_existing_vcn ? 0 : 1
  display_name   = "${local.cluster_name}_private_route_table"
  compartment_id = var.targetCompartment
  vcn_id         = oci_core_vcn.vcn[0].id

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.ng1[0].id
  }

  route_rules {
    destination       = data.oci_core_services.services.services[0]["cidr_block"]
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.sg1[0].id
  }
}
resource "oci_core_dhcp_options" "cluster_dhcp_options" {
  count          = var.use_existing_vcn ? 0 : 1
  compartment_id = var.targetCompartment
  options {
        type = "DomainNameServer"
        server_type = "VcnLocalPlusInternet"
    }
  options {
        type = "SearchDomain"
        search_domain_names = [ "${var.dns_entries? local.zone_name : "cluster.oraclevcn.com"}" ]
    }
  vcn_id = oci_core_vcn.vcn[0].id
  display_name = "${local.cluster_name}_DHCP"
}
resource "oci_core_subnet" "public-subnet" {
  count               = (var.use_existing_vcn || var.private_deployment) ? 0 : 1
  # availability_domain = var.ad
  vcn_id              = oci_core_vcn.vcn[0].id
  compartment_id      = var.targetCompartment
  cidr_block          = trimspace(var.public_subnet)
  security_list_ids   = [oci_core_security_list.public-security-list[0].id]
  dns_label           = "public"
  display_name        = "${local.cluster_name}_public_subnet"
  route_table_id      = oci_core_route_table.public_route_table[0].id
  dhcp_options_id     = oci_core_dhcp_options.cluster_dhcp_options[0].id
}

resource "oci_core_subnet" "private-subnet" {
  count                      = var.use_existing_vcn ? 0 : var.private_deployment ? 2 : 1
  # availability_domain        = var.ad
  vcn_id                     = oci_core_vcn.vcn[0].id
  compartment_id             = var.targetCompartment
  cidr_block                 = trimspace(local.private_subnet_cidr[count.index])
  security_list_ids          = [oci_core_security_list.internal-security-list[0].id]
  dns_label                  = "private${count.index+1}"
  display_name               = "${local.cluster_name}_private_subnet${count.index+1}"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private_route_table[0].id
  dhcp_options_id            = oci_core_dhcp_options.cluster_dhcp_options[0].id
}

resource "oci_dns_zone" "dns_zone" {
  count          = var.use_existing_vcn ? 0 : 1
  compartment_id = var.targetCompartment
  name = "${local.cluster_name}.local" #oci_core_dhcp_options.cluster_dhcp_options[0].options.search_domain_names[0]
  zone_type = "PRIMARY"
  scope = "PRIVATE"
  view_id = data.oci_dns_views.dns_views.views[0].id
}

resource "oci_dns_rrset" "rrset-cluster-network-OCI" {
  for_each        = var.dns_entries ? toset([for v in range(var.node_count) : tostring(v)]) : []
  zone_name_or_id = data.oci_dns_zones.dns_zones.zones[0].id
  domain          = "${local.cluster_instances_names[tonumber(each.key)]}.${local.zone_name}"
  rtype           = "A"
  items {
    domain = "${local.cluster_instances_names[tonumber(each.key)]}.${local.zone_name}"
    rtype  = "A"
    rdata  = "${local.cluster_instances_ips[tonumber(each.key)]}"
    ttl    = 3600
  }
  scope = "PRIVATE"
  view_id = data.oci_dns_views.dns_views.views[0].id
}

resource "oci_dns_rrset" "rrset-cluster-network-SLURM" {
  
  for_each        = var.slurm && var.dns_entries ? toset([for v in range(var.node_count) : tostring(v)]) : []
  zone_name_or_id = data.oci_dns_zones.dns_zones.zones[0].id
  domain          = "${var.queue}-permanent-${local.cluster_instances_ips_index[tonumber(each.key)]}.${local.zone_name}"
  rtype           = "A"
  items {
    domain = "${var.queue}-permanent-${local.cluster_instances_ips_index[tonumber(each.key)]}.${local.zone_name}"
    rtype  = "A"
    rdata  = "${local.cluster_instances_ips[tonumber(each.key)]}"
    ttl    = 3600
  }
  scope = "PRIVATE"
  view_id = data.oci_dns_views.dns_views.views[0].id
}


resource "oci_dns_rrset" "fss-dns-round-robin" {
  count           = var.create_fss && var.dns_entries ? 1 : 0
  zone_name_or_id = data.oci_dns_zones.dns_zones.zones[0].id
  domain          = "fss-${local.cluster_name}.${local.zone_name}"
  rtype           = "A"

  dynamic "items" {
    for_each = oci_file_storage_mount_target.FSSMountTarget[*]
    iterator = target
    content {
      domain = "fss-${local.cluster_name}.${local.zone_name}"
      rtype  = "A"
      rdata  = target.value["ip_address"]
      ttl    = 1
    }
  }
  scope   = "PRIVATE"
  view_id = data.oci_dns_views.dns_views.views[0].id
}

