# Test-only SSH keys

`a` and `b` are OpenSSH ed25519 private keys, committed on purpose. `a.pub` and `b.pub` are
their public halves.

They are throwaway keys generated for the Biolean ledger signature-verification fixtures.
They have never been used for anything else and grant access to nothing.

The code treats them as untrusted outside the fixtures: their digests are pinned in
`FIXTURE_KEY_DIGESTS` (`src/methods_graph/biolean/sshsig.py`), and `mg biolean ledger init`
refuses them.

Do not regenerate them. The signed fixtures in `../known/`, `../signed/`,
`../signed-variants/` and `../sigs/` were made with these exact keys.
