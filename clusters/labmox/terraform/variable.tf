variable "proxmox_endpoint" {
  type = string
}

variable "proxmox_username" {
  type = string
}

variable "proxmox_address" {
  type = string
}

variable "proxmox_ssh_port" {
  type = number
}

variable "token" {
  type = string
}

variable "node_name" {
  type = string
}

variable "nodes" {
  type = map(object({
    vm_id     = number
    memory    = number
    cpu       = number
    role      = string
    ipv4      = string
    main_disk = number
    disks     = list(number)
  }))
}
