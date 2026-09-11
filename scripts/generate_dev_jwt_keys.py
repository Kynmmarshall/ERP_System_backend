"""Generates a dev-only RSA keypair for signing/verifying JWTs.

Run once per machine with the identity service's venv active (it already has
`cryptography` via pyjwt[crypto]):

    cd services/identity
    .venv\\Scripts\\python.exe ..\\..\\scripts\\generate_dev_jwt_keys.py

Writes ops/secrets/dev/jwt_private_key.pem (identity only) and
jwt_public_key.pem (mounted read-only into every service). Never commit these
files or reuse them outside local development - production keys must be
generated and stored the same way but distributed via Jenkins credentials /
the VPS secret files, never through Git.
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ops" / "secrets" / "dev"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    (OUTPUT_DIR / "jwt_private_key.pem").write_bytes(private_bytes)
    (OUTPUT_DIR / "jwt_public_key.pem").write_bytes(public_bytes)
    print(f"Wrote dev JWT keypair to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
