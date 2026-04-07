#!/bin/bash
set -e

export CONTROL_PLANE_IP=${1:-10.1.2.90}
export CLUSTER_NAME=${2:-labmox}

echo "🚀 Bootstrapping Talos Cluster: $CLUSTER_NAME at $CONTROL_PLANE_IP"

echo "📦 Generating secrets and base config..."
talosctl gen secrets -o secrets.yaml
talosctl gen config --with-secrets secrets.yaml $CLUSTER_NAME https://$CONTROL_PLANE_IP:6443

echo "🧩 Merging patches into controlplane.yaml..."
talosctl machineconfig patch controlplane.yaml --patch @patches/controlplane-patch-1.yaml --output controlplane.yaml
talosctl machineconfig patch controlplane.yaml --patch @patches/user-volume.patch.yaml --output controlplane.yaml

echo "🚢 Applying config to node..."
talosctl apply-config --insecure --nodes $CONTROL_PLANE_IP --file controlplane.yaml

echo "⚙️ Configuring local talosctl..."
mkdir -p ~/.talos/
cp ./talosconfig ~/.talos/config
talosctl config endpoint $CONTROL_PLANE_IP
talosctl config nodes $CONTROL_PLANE_IP

echo "⏳ Waiting 30 seconds for Talos API to initialize on the node..."
sleep 30

echo "🔥 Bootstrapping etcd..."
talosctl bootstrap --nodes $CONTROL_PLANE_IP

echo "🏥 Checking cluster health (this will block until K8s is ready)..."
talosctl health --nodes $CONTROL_PLANE_IP

echo "🔑 Fetching kubeconfig..."
talosctl kubeconfig --nodes $CONTROL_PLANE_IP --force

echo "✅ Done! You can now use kubectl."