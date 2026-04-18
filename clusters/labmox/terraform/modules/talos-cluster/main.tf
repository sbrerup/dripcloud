resource "proxmox_virtual_environment_vm" "talos_nodes" {
  for_each  = var.nodes
  vm_id     = each.value.vm_id
  node_name = var.node_name
  name      = each.key
  started   = true

  clone {
    full  = true
    vm_id = 8000
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    size         = each.value.main_disk
    iothread     = true
    discard      = "on"
  }

  dynamic "disk" {
    for_each = each.value.disks

    content {
      datastore_id = "local-zfs"
      interface    = "scsi${disk.key + 1}"
      size         = disk.value
      iothread     = true
      discard      = "on"
    }
  }

  memory {
    dedicated = each.value.memory
  }

  cpu {
    cores = each.value.cpu
    type  = "host"
  }

  initialization {
    datastore_id = "local-zfs"
    ip_config {
      ipv4 {
        address = each.value.ipv4
        gateway = "10.1.2.1"
      }
    }
  }
}
