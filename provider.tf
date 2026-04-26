provider "oci" {
  region = var.region
}

provider "oci" {
  alias  = "home"
  region = local.home_region
}
