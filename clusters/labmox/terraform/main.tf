provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.token

  ssh {
    agent    = true
    username = var.proxmox_username

    node {
      name    = var.node_name
      address = var.proxmox_address
      port    = var.proxmox_ssh_port
    }
  }
}

module "talos_cluster" {
  source    = "./modules/talos-cluster"
  node_name = var.node_name
  nodes     = var.nodes
}
