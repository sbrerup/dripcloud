variable "node_name" {
  type = string
}

variable "nodes" {
  type = map(object({
    vm_id     = number
    memory    = number
    cpu       = number
    role      = string
    main_disk = number
    disks     = list(number)
    ipv4      = string
  }))
}
