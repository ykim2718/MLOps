# Ubuntu CLI

<sub>rev. 10</sub>

> Commands in this document are written for **Ubuntu**.

## 1. Users

On Ubuntu, the interactive `adduser`/`deluser` tools are recommended. (`useradd`/`userdel` also exist but require specifying each option manually.)

### 1.1 Create a user

```bash
sudo adduser username    # Create account + home directory; prompts for password and details
```

- Automatically creates the home directory (`/home/username`), a default group, and a login shell.
- Prompts interactively for the password, full name, and other details.

### 1.2 List users

```bash
getent passwd                                     # List all accounts (system + human)
cut -d: -f1 /etc/passwd                            # List just the usernames
awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd   # Human users only (UID 1000-65533)
```

- On Ubuntu, regular (human) accounts start at UID 1000; lower UIDs are system accounts.
- `who` / `w` — Show users currently logged in (not all accounts).

### 1.3 Verify a user

```bash
id username              # Show UID, GID, and group membership
getent passwd username   # Show the /etc/passwd entry
ls -ld /home/username    # Show home directory owner and permissions
```

### 1.4 Delete a user

```bash
sudo deluser username                  # Delete account only (home directory remains)
sudo deluser --remove-home username    # Delete account together with the home directory
```

- `--remove-home` — Also removes the home directory (`/home/username`).
- Deletion may be refused if the user still has running processes. Terminate those processes first.

### 1.5 Grant sudo privileges

```bash
sudo usermod -aG sudo username   # Add the user to the sudo group
```

- On Ubuntu, the administrator (sudo) group is named `sudo`.
- `-aG` — Adds to the given group (`-G`) while keeping existing groups (`-a`). Using `-G` without `-a` replaces all existing supplementary groups, so be careful.

## 2. Files & Permissions

### 2.1 Change ownership

Change the owner of everything in the current directory (for example, from `root` to a specific user):

```bash
sudo chown -R username:username .    # Recursively set owner and group to username
```

- `-R` — Recursive; applies to all files and subdirectories underneath.
- `username:username` — `owner:group` format; changes the group as well.
- `.` — The current directory. Use an explicit path (`/path/to/dir`) if preferred.

Variants:

```bash
sudo chown -R username .        # Change owner only (leave group unchanged)
sudo chown -R username: .       # Change owner and set group to username's primary group
sudo chown -R :groupname .      # Change group only
```

- Target `.` (not `./*`) to include the current directory itself and hidden dotfiles; `./*` skips names starting with `.`.
- By default only the symlink itself is changed, not its target.
- Check before and after with `ls -la`.

## 3. Network

### 3.1 Show IP addresses

```bash
hostname -I                    # All IP addresses of this host, space-separated
ip addr                        # Full interface details (addresses, state, MAC)
ip -4 addr show scope global   # IPv4 addresses on external interfaces only
```

- `hostname -I` — Quickest way to get the machine's IP(s); excludes loopback (`127.0.0.1`).
- Use the LAN address (e.g. `192.168.x.x`) when connecting from another host on the same network.

### 3.2 Show MAC address

```bash
ip link                                    # MAC address (link/ether) of every interface
cat /sys/class/net/eth0/address            # MAC of a specific interface (replace eth0)
ip link show eth0                          # MAC of one interface with its state
```

- In `ip link` output, the MAC follows the `link/ether` label.
- List interface names first with `ls /sys/class/net` (e.g. `eth0`, `ens33`, `wlan0`, `lo`).
- `lo` (loopback) has a fixed all-zero MAC (`00:00:00:00:00:00`); ignore it.

### 3.3 Check connectivity and open ports

```bash
ping <host>                    # Test reachability to a host or IP
ss -tlnp                       # List listening TCP ports and owning processes
ss -tlnp | grep 8001           # Check whether a specific port is listening
```

- `ss -tlnp` shows `0.0.0.0:PORT` (all interfaces, reachable externally) vs `127.0.0.1:PORT` (local only).
