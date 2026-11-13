# KDE wallet integration

## Confirmed on the current machine

- KDE ksecretd owns org.freedesktop.secrets.
- GNOME Keyring was not running after reboot.
- Brave retained the Perplexity login.
- Zed retained the GitHub login.
- niri startup runs /usr/libexec/pam_kwallet_init.
- With that helper, no separate wallet password prompt appeared.

## Files managed by the manifest

The wallet-integration group contains desktop-specific Secret portal
preferences, the user Secret Service activation file, and a disabled
GNOME secrets-autostart entry. niri/config.kdl remains in the niri group.

## Host setup not performed by scripts/deploy.py

On the tested openSUSE host:

    sudo pam-config --delete --gnome_keyring
    systemctl --user mask gnome-keyring-daemon.service gnome-keyring-daemon.socket

KWallet PAM integration remains enabled. Review PAM configuration and
package paths before reproducing these steps on another machine.
Do not copy generated PAM files between systems.

## Hyprland follow-up

Its Secret portal preference is already captured. When configuring
Hyprland, add:

    exec-once = /usr/libexec/pam_kwallet_init

Hyprland startup and automatic unlocking have not yet been tested.

## Security boundary

No wallet databases, secrets, browser profiles, or authentication tokens
are stored here. Applications using independent storage may still need
separate integration.
