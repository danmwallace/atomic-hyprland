#!/usr/bin/bash
set -euo pipefail
theme="${1:?theme}"

# Keep every Ansible artefact under /tmp/build so nothing lands in
# /var/roothome (which bootc lint and the smoke test both reject).
export ANSIBLE_HOME=/tmp/build/ansible
export ANSIBLE_LOCAL_TEMP=/tmp/build/ansible/tmp
# /root is a symlink into /var/roothome, which does not exist at build time.
export ANSIBLE_REMOTE_TMP=/tmp/build/ansible/tmp
export ANSIBLE_COLLECTIONS_PATH=/tmp/build/collections
export ANSIBLE_NOCOWS=1

ansible-galaxy collection install -p /tmp/build/collections -r /tmp/build/requirements.yml
ansible-playbook -c local -i localhost, /tmp/build/playbook.yml -e "hyprland_theme=${theme}"
